"""Disposable tenants; real API, PostgreSQL, and worker processes. No mocked persistence."""

import asyncio
import concurrent.futures
import json
import os
import sys
import time
from uuid import uuid4

import httpx
from psycopg.types.json import Jsonb

from atlas.cli import demo_evidence
from atlas.contracts import digest
from atlas.db import pool, provision
from atlas.worker import claim, finish

base = os.environ.get("ATLAS_URL", "http://localhost:8080")
a, b = provision("Integration A"), provision("Integration B")


def request(method, path, body=None, account=a, role="investigator", key=None):
    headers = {"Authorization": "Bearer " + account[role]}
    if key:
        headers["Idempotency-Key"] = key
    with httpx.Client(timeout=20, trust_env=False) as client:
        return client.request(method, base + path, json=body, headers=headers)


def accepted(response, code=200):
    assert response.status_code == code, (response.status_code, response.text)
    return response.json()


def wait_job(job):
    for _ in range(100):
        result = accepted(request("GET", "/api/replays/" + job))
        if result["status"] in ("completed", "failed", "cancelled"):
            return result
        time.sleep(0.2)
    raise AssertionError("replay failed to reach terminal state")


with pool() as db:
    try:
        bad = demo_evidence(503)
        bad["spans"][0]["attributes"]["authorization"] = "MUST-NOT-PERSIST"
        good = demo_evidence(200)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as threads:
            results = list(threads.map(lambda _: request("POST", "/api/executions", bad), range(8)))
        assert sorted(r.status_code for r in results) == [200] * 7 + [201]
        accepted(request("POST", "/api/executions", good), 201)
        clash = {**bad, "name": "different"}
        accepted(request("POST", "/api/executions", clash), 409)
        data = accepted(request("GET", "/api/executions/" + bad["id"]))
        assert "MUST-NOT-PERSIST" not in json.dumps(data)
        accepted(request("GET", "/api/executions/" + bad["id"], account=b), 404)
        accepted(request("GET", "/api/executions", role="ingestor"), 403)
        accepted(request("POST", "/api/executions", good, role="reader"), 403)
        accepted(request("GET", "/api/metrics", role="reader"), 403)
        accepted(request("GET", f"/api/compare?left={good['id']}&right={bad['id']}", account=b), 404)
        changed = accepted(request("GET", f"/api/compare?left={good['id']}&right={bad['id']}"))
        assert any(x["service"] == "payments" and x["change"] == "changed" for x in changed["changes"])
        body = {"execution_id": bad["id"], "expected_status": 502}
        accepted(request("POST", "/api/replays", body, role="reader", key="reader-reject"), 403)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as threads:
            results = list(
                threads.map(
                    lambda _: accepted(request("POST", "/api/replays", body, key="same-key-001"), 202),
                    range(8),
                )
            )
        assert len({r["id"] for r in results}) == 1
        job = results[0]["id"]
        accepted(request("POST", "/api/replays", {**body, "expected_status": 201}, key="same-key-001"), 409)
        accepted(request("GET", "/api/replays/" + job, account=b), 404)
        assert wait_job(job)["result"]["passed"]
        repaired = accepted(
            request(
                "POST",
                "/api/replays",
                {**body, "expected_status": 201, "payment_status": 200},
                key="repair-001",
            ),
            202,
        )
        result = wait_job(repaired["id"])
        assert (
            result["status"] == "completed"
            and result["result"]["passed"]
            and not result["result"]["matches_capture"]
        )
        mismatch = accepted(
            request("POST", "/api/replays", {**body, "expected_status": 201}, key="mismatch-001"), 202
        )
        assert wait_job(mismatch["id"])["result"]["passed"] is False
        pending = accepted(
            request("POST", "/api/replays", {**body, "dependency_delay_ms": 1500}, key="cancel-001"), 202
        )
        accepted(request("POST", "/api/replays/" + pending["id"] + "/cancel"))
        time.sleep(4)
        assert wait_job(pending["id"])["status"] == "cancelled"

        async def mcp_roundtrip():
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "atlas.cli", "mcp"],
                env={"ATLAS_URL": base, "ATLAS_TOKEN": a["reader"]},
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert {t.name for t in tools.tools} == {
                        "list_executions",
                        "get_execution",
                        "compare_executions",
                        "get_replay",
                    }
                    result = await session.call_tool("get_execution", {"execution_id": bad["id"]})
                    assert not result.isError and bad["id"] in str(result.content)

        asyncio.run(mcp_roundtrip())
        # A synthetic crashed lease exercises fencing against a stale worker without timing dependence.
        synthetic = uuid4()
        with db.connection() as conn:
            conn.execute(
                """INSERT INTO replays(tenant_id,id,execution_id,idempotency_key,request_digest,request,evidence,
                status,attempts,lease_token,lease_until) VALUES (%s,%s,%s,%s,%s,%s,%s,'running',1,%s,now()-interval '1 second')""",
                (
                    a["tenant_id"],
                    synthetic,
                    bad["id"],
                    str(synthetic),
                    digest(body),
                    Jsonb(body),
                    Jsonb(data),
                    uuid4(),
                ),
            )
            reclaimed = claim(conn)
            assert reclaimed and reclaimed["id"] == synthetic
            stale = {**reclaimed, "lease_token": uuid4()}
            assert not finish(conn, stale, {"passed": True})
            assert finish(conn, reclaimed, {"passed": True})
        events = accepted(request("GET", "/api/audit"))["items"]
        assert any(e["action"] == "replay.completed" for e in events)
        with db.connection() as conn:
            from atlas.db import token_digest

            conn.execute("UPDATE credentials SET revoked=true WHERE digest=%s", (token_digest(b["reader"]),))
        accepted(request("GET", "/api/executions", account=b, role="reader"), 401)
        print(
            "PASS: concurrent ingestion, conflicts, redaction, tenant/RBAC isolation, replay dedupe, real HTTP replay, assertion failure, cancellation, lease recovery, fencing, audit and revocation"
        )
    finally:
        with db.connection() as conn:
            for account in (a, b):
                conn.execute("DELETE FROM audit WHERE tenant_id=%s", (account["tenant_id"],))
                conn.execute("DELETE FROM replays WHERE tenant_id=%s", (account["tenant_id"],))
                conn.execute("DELETE FROM executions WHERE tenant_id=%s", (account["tenant_id"],))
                conn.execute("DELETE FROM credentials WHERE tenant_id=%s", (account["tenant_id"],))
                conn.execute("DELETE FROM tenants WHERE id=%s", (account["tenant_id"],))
