import json
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CollectorRegistry, Gauge, generate_latest
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout

from atlas.contracts import Execution, ReplayRequest, compare, digest, outcome, sanitize
from atlas.db import pool, token_digest


@asynccontextmanager
async def lifespan(app):
    app.state.db = pool()
    try:
        yield
    finally:
        app.state.db.close()


app = FastAPI(title="Trace Atlas", version="0.1.0", lifespan=lifespan)


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > 262144:
                return await JSONResponse({"detail": "body exceeds 256 KiB"}, 413)(scope, receive, send)
            messages.append(message)
            if not message.get("more_body"):
                break

        async def bounded_receive():
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, bounded_receive, send)


app.add_middleware(BodyLimit)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    # Do not echo submitted evidence or bearer credentials in validation errors.
    return JSONResponse(
        {
            "detail": "invalid request",
            "errors": [{"location": e["loc"], "type": e["type"]} for e in exc.errors()],
        },
        422,
    )


@app.exception_handler(PoolTimeout)
@app.exception_handler(psycopg.Error)
async def database_error(request, exc):
    return JSONResponse({"detail": "database unavailable; retry with the same idempotency key"}, 503)


def connection(request: Request):
    with request.app.state.db.connection() as conn:
        yield conn


def principal(authorization: str = Header(default=""), conn=Depends(connection)):
    if not authorization.startswith("Bearer ") or not 20 <= len(authorization[7:]) <= 200:
        raise HTTPException(401, "bearer credential required", headers={"WWW-Authenticate": "Bearer"})
    row = conn.execute(
        "SELECT tenant_id,role FROM credentials WHERE digest=%s AND NOT revoked",
        (token_digest(authorization[7:]),),
    ).fetchone()
    if not row:
        raise HTTPException(401, "invalid credential", headers={"WWW-Authenticate": "Bearer"})
    return row


def reader(p=Depends(principal)):
    if p["role"] not in ("reader", "investigator"):
        raise HTTPException(403, "read permission required")
    return p


def investigator(p=Depends(principal)):
    if p["role"] != "investigator":
        raise HTTPException(403, "investigator permission required")
    return p


def evidence(conn, tenant, execution_id):
    row = conn.execute(
        "SELECT evidence FROM executions WHERE tenant_id=%s AND id=%s", (tenant, execution_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "execution not found")
    return row["evidence"]


def audit(conn, tenant, action, resource):
    conn.execute(
        "INSERT INTO audit(tenant_id,action,resource_id) VALUES (%s,%s,%s)", (tenant, action, resource)
    )


@app.get("/health/live")
def live():
    return {"status": "up"}


@app.get("/health/ready")
def ready(conn=Depends(connection)):
    conn.execute("SELECT 1 FROM schema_version WHERE version=1").fetchone()
    return {"status": "ready"}


@app.get("/api/me")
def me(p=Depends(principal)):
    return p


@app.get("/api/metrics")
def metrics(p=Depends(investigator), conn=Depends(connection)):
    registry = CollectorRegistry()
    evidence_count = conn.execute(
        "SELECT count(*) n FROM executions WHERE tenant_id=%s", (p["tenant_id"],)
    ).fetchone()["n"]
    Gauge("atlas_executions_stored", "Current tenant evidence snapshots", registry=registry).set(
        evidence_count
    )
    jobs = Gauge("atlas_replays", "Current tenant replay jobs", ["status"], registry=registry)
    for row in conn.execute(
        "SELECT status,count(*) n FROM replays WHERE tenant_id=%s GROUP BY status", (p["tenant_id"],)
    ):
        jobs.labels(row["status"]).set(row["n"])
    return Response(generate_latest(registry), media_type="text/plain; version=0.0.4")


@app.post("/api/executions", status_code=201)
def ingest(item: Execution, response: Response, p=Depends(principal), conn=Depends(connection)):
    if p["role"] not in ("ingestor", "investigator"):
        raise HTTPException(403, "ingest permission required")
    data = sanitize(item)
    fingerprint = digest(data)
    # Serialize quota decisions per tenant; uniqueness still enforced by the database.
    conn.execute("SELECT id FROM tenants WHERE id=%s FOR UPDATE", (p["tenant_id"],))
    old = conn.execute(
        "SELECT digest FROM executions WHERE tenant_id=%s AND id=%s", (p["tenant_id"], item.id)
    ).fetchone()
    if old:
        if old["digest"] != fingerprint:
            raise HTTPException(409, "execution ID already has different sanitized evidence")
        response.status_code = 200
        return {"id": item.id, "duplicate": True, "digest": fingerprint}
    count = conn.execute(
        "SELECT count(*) n FROM executions WHERE tenant_id=%s", (p["tenant_id"],)
    ).fetchone()["n"]
    if count >= 10000:
        raise HTTPException(429, "tenant evidence limit reached; apply retention before retrying")
    conn.execute(
        "INSERT INTO executions(tenant_id,id,name,outcome,version,digest,evidence) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (p["tenant_id"], item.id, item.name, outcome(data), item.version, fingerprint, Jsonb(data)),
    )
    audit(conn, p["tenant_id"], "execution.accepted", item.id)
    return {"id": item.id, "duplicate": False, "digest": fingerprint}


@app.get("/api/executions")
def executions(
    q: str = Query(default="", max_length=80),
    outcome_filter: str = Query(default="", pattern="^(ok|error)?$"),
    offset: int = Query(default=0, ge=0, le=10000),
    limit: int = Query(default=30, ge=1, le=100),
    p=Depends(reader),
    conn=Depends(connection),
):
    rows = conn.execute(
        """SELECT id,name,outcome,version,created_at,jsonb_array_length(evidence->'spans') span_count
        FROM executions WHERE tenant_id=%s AND (%s='' OR outcome=%s) AND position(lower(%s) in lower(name))>0
        ORDER BY created_at DESC,id LIMIT %s OFFSET %s""",
        (p["tenant_id"], outcome_filter, outcome_filter, q, limit, offset),
    ).fetchall()
    return {
        "items": rows,
        "next_offset": offset + limit if len(rows) == limit and offset + limit <= 10000 else None,
    }


@app.get("/api/executions/{execution_id}")
def execution(execution_id: UUID, p=Depends(reader), conn=Depends(connection)):
    return evidence(conn, p["tenant_id"], execution_id)


@app.get("/api/compare")
def comparison(left: UUID, right: UUID, p=Depends(reader), conn=Depends(connection)):
    return compare(evidence(conn, p["tenant_id"], left), evidence(conn, p["tenant_id"], right))


@app.get("/api/executions/{execution_id}/export")
def export(execution_id: UUID, p=Depends(reader), conn=Depends(connection)):
    data = evidence(conn, p["tenant_id"], execution_id)
    return Response(
        json.dumps(data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="execution-{execution_id}.json"'},
    )


@app.post("/api/replays", status_code=202)
def replay(
    item: ReplayRequest,
    idempotency_key: str = Header(min_length=8, max_length=100),
    p=Depends(investigator),
    conn=Depends(connection),
):
    tenant = p["tenant_id"]
    request = item.model_dump(mode="json")
    fingerprint = digest(request)
    conn.execute("SELECT id FROM tenants WHERE id=%s FOR UPDATE", (tenant,))
    old = conn.execute(
        "SELECT id,request_digest FROM replays WHERE tenant_id=%s AND idempotency_key=%s",
        (tenant, idempotency_key),
    ).fetchone()
    if old:
        if old["request_digest"] != fingerprint:
            raise HTTPException(409, "idempotency key reused with different request")
        return {"id": old["id"], "duplicate": True}
    data = evidence(conn, tenant, item.execution_id)
    if data.get("fixture") is None:
        raise HTTPException(422, "execution has no supported checkout-v1 fixture")
    active = conn.execute(
        "SELECT count(*) n FROM replays WHERE tenant_id=%s AND status IN ('queued','running')", (tenant,)
    ).fetchone()["n"]
    if active >= 20:
        raise HTTPException(429, "tenant active replay limit reached")
    job = uuid4()
    conn.execute(
        """INSERT INTO replays(tenant_id,id,execution_id,idempotency_key,request_digest,request,evidence)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (tenant, job, item.execution_id, idempotency_key, fingerprint, Jsonb(request), Jsonb(data)),
    )
    audit(conn, tenant, "replay.created", job)
    return {"id": job, "duplicate": False}


@app.get("/api/replays")
def replays(p=Depends(reader), conn=Depends(connection)):
    return {
        "items": conn.execute(
            """SELECT id,execution_id,status,attempts,result,created_at,updated_at
        FROM replays WHERE tenant_id=%s ORDER BY created_at DESC,id LIMIT 50""",
            (p["tenant_id"],),
        ).fetchall()
    }


@app.get("/api/replays/{job_id}")
def replay_detail(job_id: UUID, p=Depends(reader), conn=Depends(connection)):
    row = conn.execute(
        """SELECT id,execution_id,status,attempts,request,result,created_at,updated_at
        FROM replays WHERE tenant_id=%s AND id=%s""",
        (p["tenant_id"], job_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "replay not found")
    return row


@app.post("/api/replays/{job_id}/cancel")
def cancel(job_id: UUID, p=Depends(investigator), conn=Depends(connection)):
    row = conn.execute(
        """UPDATE replays SET status='cancelled',lease_token=NULL,lease_until=NULL,updated_at=now()
        WHERE tenant_id=%s AND id=%s AND status IN ('queued','running') RETURNING id""",
        (p["tenant_id"], job_id),
    ).fetchone()
    if not row:
        raise HTTPException(409, "replay absent or already terminal")
    audit(conn, p["tenant_id"], "replay.cancelled", job_id)
    return {"id": job_id, "status": "cancelled"}


@app.get("/api/audit")
def audit_log(p=Depends(investigator), conn=Depends(connection)):
    return {
        "items": conn.execute(
            "SELECT action,resource_id,created_at FROM audit WHERE tenant_id=%s ORDER BY id DESC LIMIT 100",
            (p["tenant_id"],),
        ).fetchall()
    }
