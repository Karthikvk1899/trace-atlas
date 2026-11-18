import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_EVIDENCE_BYTES = 256 * 1024


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Span(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    parent_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    service: str = Field(pattern=r"^[a-zA-Z0-9._-]{1,64}$")
    operation: str = Field(min_length=1, max_length=120)
    start_ms: int = Field(ge=0, le=86_400_000)
    duration_ms: int = Field(ge=0, le=3_600_000)
    status: Literal["ok", "error"]
    http_status: int | None = Field(default=None, ge=100, le=599)
    attributes: dict[str, str | int | bool] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def attributes_bounded(self):
        if any(len(k) > 64 or len(str(v)) > 256 for k, v in self.attributes.items()):
            raise ValueError("attribute exceeds size limit")
        return self


class Fixture(Strict):
    inventory_status: int = Field(ge=200, le=599)
    payment_status: int = Field(ge=200, le=599)
    captured_checkout_status: int = Field(ge=200, le=599)
    quantity: int = Field(ge=1, le=100)


class Execution(Strict):
    schema_version: Literal[1] = 1
    id: UUID
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=80)
    spans: list[Span] = Field(min_length=1, max_length=200)
    fixture: Fixture | None = None

    @model_validator(mode="after")
    def graph(self):
        nodes = {s.id: s for s in self.spans}
        if len(nodes) != len(self.spans):
            raise ValueError("duplicate span id")
        roots = [s for s in self.spans if s.parent_id is None]
        if len(roots) != 1:
            raise ValueError("exactly one root required")
        for span in self.spans:
            seen = set()
            cursor = span
            while cursor.parent_id is not None:
                if cursor.id in seen or cursor.parent_id not in nodes:
                    raise ValueError("cyclic graph or missing parent")
                seen.add(cursor.id)
                cursor = nodes[cursor.parent_id]
        return self


class ReplayRequest(Strict):
    execution_id: UUID
    expected_status: int = Field(ge=200, le=599)
    inventory_status: int | None = Field(default=None, ge=200, le=599)
    payment_status: int | None = Field(default=None, ge=200, le=599)
    dependency_delay_ms: int = Field(default=0, ge=0, le=1500)


SAFE_ATTRIBUTES = {
    "http.method",
    "http.route",
    "messaging.system",
    "messaging.destination",
    "error.type",
    "deployment.version",
    "db.operation",
}


def sanitize(execution):
    data = execution.model_dump(mode="json")
    # An allowlist deliberately excludes headers, bodies, queries, user IDs and credentials.
    for span in data["spans"]:
        span["attributes"] = {k: v for k, v in span["attributes"].items() if k in SAFE_ATTRIBUTES}
    return data


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def outcome(data):
    return "error" if any(s["status"] == "error" for s in data["spans"]) else "ok"


def compare(left, right):
    def index(data):
        result = {}
        for span in sorted(data["spans"], key=lambda s: (s["start_ms"], s["id"])):
            key = (span["service"], span["operation"])
            result.setdefault(key, []).append(span)
        return result

    a, b = index(left), index(right)
    changes = []
    for key in sorted(a.keys() | b.keys()):
        for i in range(max(len(a.get(key, [])), len(b.get(key, [])))):
            x = a.get(key, [])[i] if i < len(a.get(key, [])) else None
            y = b.get(key, [])[i] if i < len(b.get(key, [])) else None
            changes.append(
                {
                    "service": key[0],
                    "operation": key[1],
                    "occurrence": i + 1,
                    "left_span": x["id"] if x else None,
                    "right_span": y["id"] if y else None,
                    "change": "added"
                    if not x
                    else "removed"
                    if not y
                    else "changed"
                    if (x["status"], x["http_status"]) != (y["status"], y["http_status"])
                    else "same",
                    "duration_delta_ms": y["duration_ms"] - x["duration_ms"] if x and y else None,
                    "left_status": x["http_status"] if x else None,
                    "right_status": y["http_status"] if y else None,
                }
            )
    return {
        "alignment": "service + operation + chronological occurrence; not causal proof",
        "changes": changes,
    }
