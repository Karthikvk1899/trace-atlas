"""Destructive only to this disposable Compose stack. Never point at production."""

import json
import subprocess
import time
import urllib.error
import urllib.request
from uuid import uuid4


def compose(*args, data=None):
    return subprocess.run(["docker", "compose", *args], input=data, capture_output=True, check=True).stdout


def api(path, token, body=None, key=None):
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    if key:
        headers["Idempotency-Key"] = key
    request = urllib.request.Request(
        "http://127.0.0.1:8080" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)


def await_ready():
    for _ in range(60):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/health/ready", timeout=8) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(1)
    raise AssertionError("database/API did not recover")


account = json.loads(compose("exec", "-T", "api", "atlas", "tenant", "Operations rehearsal"))
token = account["investigator"]
fixture = json.loads(
    compose(
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        "import json; from atlas.cli import demo_evidence; print(json.dumps(demo_evidence(503)))",
    )
)
api("/api/executions", token, fixture)
restore = "atlas_restore_" + uuid4().hex
created = False
try:
    compose("stop", "worker")
    job = api(
        "/api/replays", token, {"execution_id": fixture["id"], "expected_status": 502}, "recovery-key-001"
    )["id"]
    assert api("/api/replays/" + job, token)["status"] == "queued"
    compose("restart", "api")
    await_ready()
    assert api("/api/executions/" + fixture["id"], token)["id"] == fixture["id"]
    assert api("/api/replays/" + job, token)["status"] == "queued"
    compose("start", "worker")
    for _ in range(100):
        result = api("/api/replays/" + job, token)
        if result["status"] == "completed":
            assert result["result"]["passed"]
            break
        time.sleep(0.2)
    else:
        raise AssertionError("queued replay did not recover")
    compose("stop", "postgres")
    try:
        api("/api/executions", token)
        raise AssertionError("database outage must not return success")
    except urllib.error.HTTPError as exc:
        assert exc.code == 503, exc.code
    finally:
        compose("start", "postgres")
    await_ready()
    assert api("/api/replays/" + job, token)["result"]["passed"]
    backup = compose("exec", "-T", "postgres", "pg_dump", "-U", "atlas", "-d", "atlas", "-Fc")
    compose("exec", "-T", "postgres", "createdb", "-U", "atlas", restore)
    created = True
    compose(
        "exec", "-T", "postgres", "pg_restore", "-U", "atlas", "-d", restore, "--exit-on-error", data=backup
    )
    query = "SELECT digest FROM executions WHERE id='" + fixture["id"] + "'"
    original = compose("exec", "-T", "postgres", "psql", "-U", "atlas", "-d", "atlas", "-Atc", query)
    restored = compose("exec", "-T", "postgres", "psql", "-U", "atlas", "-d", restore, "-Atc", query)
    assert original.strip() and restored == original
    query = "SELECT status,result->>'passed' FROM replays WHERE id='" + job + "'"
    assert (
        compose("exec", "-T", "postgres", "psql", "-U", "atlas", "-d", restore, "-Atc", query).strip()
        == b"completed|true"
    )
    assert (
        int(
            compose(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "atlas",
                "-d",
                restore,
                "-Atc",
                "SELECT count(*) FROM credentials",
            )
        )
        >= 3
    )
    print(
        "PASS: queued job survived API restart; workers recovered it; PostgreSQL outage returned 503; "
        "restored evidence digest, replay result, and credential rows verified in disposable database"
    )
finally:
    compose("start", "postgres", "worker")
    if created:
        compose("exec", "-T", "postgres", "dropdb", "-U", "atlas", restore)
