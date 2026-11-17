import json
import logging
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from psycopg import Error as DatabaseError
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout

from atlas.db import pool

log = logging.getLogger("atlas.worker")
running = True


def claim(conn):
    # Exhausted crashed jobs become terminal instead of looping forever.
    conn.execute("""UPDATE replays SET status='failed',result='{"error":"worker lease exhausted"}'::jsonb,
        lease_token=NULL,lease_until=NULL,updated_at=now()
        WHERE status='running' AND lease_until<now() AND attempts>=3""")
    token = uuid4()
    return conn.execute(
        """WITH candidate AS (
        SELECT tenant_id,id FROM replays WHERE attempts<3 AND
        (status='queued' OR (status='running' AND lease_until<now()))
        ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
        UPDATE replays r SET status='running',attempts=attempts+1,lease_token=%s,
        lease_until=now()+interval '30 seconds',updated_at=now()
        FROM candidate c WHERE r.tenant_id=c.tenant_id AND r.id=c.id
        RETURNING r.*""",
        (token,),
    ).fetchone()


def finish(conn, job, result, failed=False):
    row = conn.execute(
        """UPDATE replays SET status=%s,result=%s,lease_token=NULL,lease_until=NULL,updated_at=now()
        WHERE tenant_id=%s AND id=%s AND lease_token=%s AND status='running' AND lease_until>now()
        RETURNING id""",
        ("failed" if failed else "completed", Jsonb(result), job["tenant_id"], job["id"], job["lease_token"]),
    ).fetchone()
    if row:
        conn.execute(
            "INSERT INTO audit(tenant_id,action,resource_id) VALUES (%s,%s,%s)",
            (job["tenant_id"], "replay.failed" if failed else "replay.completed", job["id"]),
        )
    return bool(row)


def execute(job):
    payload = json.dumps({"fixture": job["evidence"]["fixture"], "options": job["request"]})
    # Fixed executable and adapter; no tenant-controlled environment, path or command.
    result = subprocess.run(
        [sys.executable, "-I", str(Path(__file__).with_name("replay_runner.py"))],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
        timeout=12,
        env={"PYTHONUNBUFFERED": "1"},
    )
    if result.returncode or len(result.stdout) > 32768:
        raise RuntimeError("adapter failed")
    return json.loads(result.stdout)


def stop(*_):
    global running
    running = False


def main():
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with pool() as db:
        while running:
            try:
                with db.connection() as conn:
                    job = claim(conn)
                if not job:
                    time.sleep(0.25)
                    continue
                try:
                    result, failed = execute(job), False
                except (subprocess.SubprocessError, ValueError, RuntimeError, OSError):
                    result, failed = {"error": "bounded adapter failed or timed out"}, True
                with db.connection() as conn:
                    finish(conn, job, result, failed)
            except (DatabaseError, PoolTimeout):
                log.error("worker database operation failed; leased work will be reclaimed")
                time.sleep(1)


if __name__ == "__main__":
    main()
