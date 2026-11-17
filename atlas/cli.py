import argparse
import json
import os
import sys
from uuid import uuid4

import httpx

from atlas.db import migrate, provision


def call(method, path, data=None, key=None):
    token = os.environ.get("ATLAS_TOKEN", "")
    if not token:
        raise ValueError("set ATLAS_TOKEN; credentials are never accepted as CLI arguments")
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    base = os.environ.get("ATLAS_URL", "http://localhost:8080").rstrip("/")
    with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
        response = client.request(method, base + path, headers=headers, json=data)
        if response.status_code >= 300:
            raise ValueError(f"API returned {response.status_code}: {response.text[:500]}")
        return response.json()


def demo_evidence(payment=503):
    from atlas.replay_runner import run

    fixture = {
        "inventory_status": 200,
        "payment_status": payment,
        "captured_checkout_status": 201 if 200 <= payment < 300 else 502,
        "quantity": 1,
    }
    observed = run(fixture, {"expected_status": fixture["captured_checkout_status"]})
    spans = [
        {
            "id": "checkout",
            "parent_id": None,
            "service": "checkout",
            "operation": "POST /checkout",
            "start_ms": 0,
            "duration_ms": observed["elapsed_ms"],
            "status": "ok" if observed["observed_status"] < 400 else "error",
            "http_status": observed["observed_status"],
            "attributes": {"http.method": "POST"},
        }
    ]
    for i, event in enumerate(observed["calls"]):
        spans.append(
            {
                "id": f"call-{i}",
                "parent_id": "checkout",
                "service": event["service"],
                "operation": "POST " + event["path"],
                "start_ms": event["start_ms"],
                "duration_ms": event["duration_ms"],
                "status": "ok" if event["status"] < 400 else "error",
                "http_status": event["status"],
                "attributes": {"http.method": "POST"},
            }
        )
    return {
        "schema_version": 1,
        "id": str(uuid4()),
        "name": "Checkout · payment accepted" if payment == 200 else "Checkout · payment unavailable",
        "version": "checkout-v1",
        "spans": spans,
        "fixture": fixture,
    }


def main():
    parser = argparse.ArgumentParser(description="Trace Atlas evidence and replay CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    tenant = sub.add_parser("tenant")
    tenant.add_argument("name")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("file")
    show = sub.add_parser("show")
    show.add_argument("id")
    sub.add_parser("list")
    diff = sub.add_parser("compare")
    diff.add_argument("left")
    diff.add_argument("right")
    replay = sub.add_parser("replay")
    replay.add_argument("id")
    replay.add_argument("--expect", type=int, required=True)
    replay.add_argument("--payment", type=int)
    replay.add_argument("--key", required=True)
    job = sub.add_parser("job")
    job.add_argument("id")
    sub.add_parser("demo")
    sub.add_parser("mcp")
    args = parser.parse_args()
    try:
        if args.command == "migrate":
            migrate()
            result = {"schema_version": 1}
        elif args.command == "tenant":
            result = provision(args.name)
        elif args.command == "ingest":
            with open(args.file) as handle:
                text = handle.read(262145)
            if len(text.encode()) > 262144:
                raise ValueError("evidence exceeds 256 KiB")
            result = call("POST", "/api/executions", json.loads(text))
        elif args.command == "list":
            result = call("GET", "/api/executions")
        elif args.command == "show":
            from uuid import UUID

            result = call("GET", f"/api/executions/{UUID(args.id)}")
        elif args.command == "compare":
            from uuid import UUID

            result = call("GET", f"/api/compare?left={UUID(args.left)}&right={UUID(args.right)}")
        elif args.command == "replay":
            result = call(
                "POST",
                "/api/replays",
                {"execution_id": args.id, "expected_status": args.expect, "payment_status": args.payment},
                args.key,
            )
        elif args.command == "job":
            from uuid import UUID

            result = call("GET", f"/api/replays/{UUID(args.id)}")
        elif args.command == "demo":
            result = [call("POST", "/api/executions", demo_evidence(status)) for status in (200, 503)]
        else:
            from atlas.mcp_server import main as serve

            serve()
            return
        print(json.dumps(result, indent=2, default=str))
    except (ValueError, OSError, httpx.HTTPError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
