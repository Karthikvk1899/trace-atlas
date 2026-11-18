import argparse
import json
import os
import sys
from uuid import uuid4

import httpx
from pydantic import ValidationError

from atlas.contracts import MAX_EVIDENCE_BYTES, Execution, compare, digest, outcome, sanitize
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


def read_evidence(path):
    with open(path, "rb") as handle:
        raw = handle.read(MAX_EVIDENCE_BYTES + 1)
    if len(raw) > MAX_EVIDENCE_BYTES:
        raise ValueError("evidence exceeds 256 KiB")
    return json.loads(raw.decode("utf-8"))


def validate_evidence(data):
    execution = Execution.model_validate(data)
    evidence = sanitize(execution)
    return {
        "id": evidence["id"],
        "digest": digest(evidence),
        "outcome": outcome(evidence),
        "span_count": len(execution.spans),
        "attributes_removed": sum(len(span.attributes) for span in execution.spans)
        - sum(len(span["attributes"]) for span in evidence["spans"]),
    }


def check_regressions(baseline, candidate, max_slowdown_ms):
    left = sanitize(Execution.model_validate(baseline))
    right = sanitize(Execution.model_validate(candidate))
    left_spans = {span["id"]: span for span in left["spans"]}
    right_spans = {span["id"]: span for span in right["spans"]}
    comparison = compare(left, right)
    regressions = []
    for change in comparison["changes"]:
        before = left_spans.get(change["left_span"])
        after = right_spans.get(change["right_span"])
        if after is None:
            reasons = ["span_removed"]
        else:
            reasons = []
            if after["status"] == "error" and (before is None or before["status"] != "error"):
                reasons.append("new_span_error")
            delta = change["duration_delta_ms"]
            if max_slowdown_ms is not None and delta is not None and delta > max_slowdown_ms:
                reasons.append("slowdown")
        if reasons:
            regressions.append({**change, "reasons": reasons})
    return {"passed": not regressions, "alignment": comparison["alignment"], "regressions": regressions}


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
    validate = sub.add_parser("validate", help="check evidence locally and preview its stored fingerprint")
    validate.add_argument("file")
    show = sub.add_parser("show")
    show.add_argument("id")
    sub.add_parser("list")
    diff = sub.add_parser("compare")
    diff.add_argument("left")
    diff.add_argument("right")
    check = sub.add_parser("check", help="compare evidence files and fail on regressions")
    check.add_argument("baseline")
    check.add_argument("candidate")
    check.add_argument("--max-slowdown-ms", type=int)
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
    exit_code = 0
    try:
        if args.command == "migrate":
            migrate()
            result = {"schema_version": 1}
        elif args.command == "tenant":
            result = provision(args.name)
        elif args.command == "ingest":
            result = call("POST", "/api/executions", read_evidence(args.file))
        elif args.command == "validate":
            result = validate_evidence(read_evidence(args.file))
        elif args.command == "list":
            result = call("GET", "/api/executions")
        elif args.command == "show":
            from uuid import UUID

            result = call("GET", f"/api/executions/{UUID(args.id)}")
        elif args.command == "compare":
            from uuid import UUID

            result = call("GET", f"/api/compare?left={UUID(args.left)}&right={UUID(args.right)}")
        elif args.command == "check":
            if args.max_slowdown_ms is not None and args.max_slowdown_ms < 0:
                raise ValueError("--max-slowdown-ms must be nonnegative")
            result = check_regressions(
                read_evidence(args.baseline), read_evidence(args.candidate), args.max_slowdown_ms
            )
            exit_code = 0 if result["passed"] else 2
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
        if exit_code:
            raise SystemExit(exit_code)
    except ValidationError as exc:
        for error in exc.errors(include_url=False, include_context=False, include_input=False):
            print(f"Invalid evidence ({error['type']}): {error['msg']}", file=sys.stderr)
        raise SystemExit(1) from None
    except (ValueError, OSError, httpx.HTTPError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
