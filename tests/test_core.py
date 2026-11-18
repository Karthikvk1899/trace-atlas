import copy
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from atlas.api import app
from atlas.cli import main
from atlas.contracts import Execution, ReplayRequest, compare, digest, sanitize
from atlas.replay_runner import run
from atlas.worker import execute


def sample():
    return {
        "id": str(uuid4()),
        "name": "checkout",
        "version": "v1",
        "spans": [
            {
                "id": "root",
                "service": "checkout",
                "operation": "POST /checkout",
                "start_ms": 0,
                "duration_ms": 20,
                "status": "error",
                "http_status": 502,
            },
            {
                "id": "payment",
                "parent_id": "root",
                "service": "payments",
                "operation": "POST /charge",
                "start_ms": 1,
                "duration_ms": 10,
                "status": "error",
                "http_status": 503,
            },
        ],
        "fixture": {
            "inventory_status": 200,
            "payment_status": 503,
            "captured_checkout_status": 502,
            "quantity": 1,
        },
    }


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "cycle", "roots", "large", "extra"])
def test_invalid_graphs_and_bounds(mutation):
    data = sample()
    if mutation == "duplicate":
        data["spans"].append(data["spans"][0])
    elif mutation == "missing":
        data["spans"][1]["parent_id"] = "absent"
    elif mutation == "cycle":
        data["spans"][1]["parent_id"] = "payment"
    elif mutation == "roots":
        data["spans"][1]["parent_id"] = None
    elif mutation == "large":
        data["spans"][1]["attributes"] = {"http.route": "x" * 257}
    else:
        data["command"] = "arbitrary code"
    with pytest.raises(ValidationError):
        Execution.model_validate(data)


def test_allowlist_removes_sensitive_attributes_before_hash():
    data = sample()
    data["spans"][0]["attributes"] = {"authorization": "secret-one", "http.method": "POST"}
    a = sanitize(Execution.model_validate(data))
    data["spans"][0]["attributes"]["authorization"] = "secret-two"
    b = sanitize(Execution.model_validate(data))
    assert a == b and digest(a) == digest(b)
    assert a["spans"][0]["attributes"] == {"http.method": "POST"}


def test_cli_validate_previews_stored_evidence_without_credentials(tmp_path, monkeypatch, capsys):
    data = sample()
    data["spans"][0]["attributes"] = {"authorization": "private-value", "http.method": "POST"}
    path = tmp_path / "execution.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.delenv("ATLAS_TOKEN", raising=False)
    monkeypatch.setattr("sys.argv", ["atlas", "validate", str(path)])

    main()

    assert json.loads(capsys.readouterr().out) == {
        "id": data["id"],
        "digest": digest(sanitize(Execution.model_validate(data))),
        "outcome": "error",
        "span_count": 2,
        "attributes_removed": 1,
    }

    data["spans"][1]["parent_id"] = "missing"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit) as failure:
        main()
    assert failure.value.code == 1
    assert "missing parent" in capsys.readouterr().err


def test_comparison_preserves_repeated_calls_and_missing_spans():
    a = sanitize(Execution.model_validate(sample()))
    b = copy.deepcopy(a)
    b["spans"][1]["http_status"] = 200
    b["spans"][1]["status"] = "ok"
    b["spans"].append({**b["spans"][1], "id": "retry", "start_ms": 15})
    result = compare(a, b)["changes"]
    assert [x["change"] for x in result if x["service"] == "payments"] == ["changed", "added"]
    assert compare(b, a)["changes"][-1]["change"] == "removed"


@pytest.mark.parametrize("inventory,payment,expected", [(200, 503, 502), (200, 200, 201), (409, 200, 409)])
def test_real_http_replay(inventory, payment, expected):
    fixture = sample()["fixture"]
    result = run(
        fixture, {"inventory_status": inventory, "payment_status": payment, "expected_status": expected}
    )
    assert result["passed"] and result["observed_status"] == expected
    assert len(result["calls"]) == (1 if inventory == 409 else 2)
    assert result["matches_capture"] == (expected == 502)


def test_failed_assertion_is_a_result_not_worker_failure():
    result = execute({"evidence": sample(), "request": {"expected_status": 201}})
    assert result["passed"] is False and result["observed_status"] == 502


@pytest.mark.parametrize(
    "data", [{"expected_status": 0}, {"dependency_delay_ms": 1501}, {"target_url": "http://localhost"}]
)
def test_replay_cannot_target_arbitrary_hosts_or_unbounded_inputs(data):
    with pytest.raises(ValidationError):
        ReplayRequest.model_validate({"execution_id": str(uuid4()), "expected_status": 201, **data})


def test_request_body_limit_runs_before_auth_or_database():
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/executions", content=b"x" * 262145)
        assert response.status_code == 413


def test_transaction_failure_cannot_return_success():
    import psycopg

    from atlas.api import app, connection

    class Connection:
        def execute(self, *args):
            return self

        def fetchone(self):
            return {"version": 1}

    def failing_commit():
        yield Connection()
        raise psycopg.OperationalError("simulated commit failure")

    app.dependency_overrides[connection] = failing_commit
    try:
        response = TestClient(app).get("/health/ready")
        assert response.status_code == 503
        assert "simulated" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_cli_check_reports_regressions_and_exit_status(tmp_path, monkeypatch, capsys):
    baseline = sample()
    baseline["spans"][0]["status"] = "ok"
    candidate = copy.deepcopy(baseline)
    candidate["spans"][0]["status"] = "error"
    candidate["spans"][0]["duration_ms"] += 51
    candidate["spans"].pop()
    baseline_file = tmp_path / "baseline.json"
    candidate_file = tmp_path / "candidate.json"
    baseline_file.write_text(json.dumps(baseline), encoding="utf-8")
    candidate_file.write_text(json.dumps(candidate), encoding="utf-8")
    monkeypatch.delenv("ATLAS_TOKEN", raising=False)
    monkeypatch.setattr(
        "sys.argv", ["atlas", "check", str(baseline_file), str(candidate_file), "--max-slowdown-ms", "50"]
    )

    with pytest.raises(SystemExit) as failure:
        main()
    assert failure.value.code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is False
    assert [row["reasons"] for row in report["regressions"]] == [
        ["new_span_error", "slowdown"],
        ["span_removed"],
    ]

    candidate_file.write_text(json.dumps(baseline), encoding="utf-8")
    main()
    assert json.loads(capsys.readouterr().out)["passed"] is True
