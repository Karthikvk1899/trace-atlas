# Contracts

Canonical machine-readable specifications are generated from code: [OpenAPI](openapi.json) and [execution JSON Schema](execution.schema.json). `python scripts/contracts.py` regenerates both; CI rejects drift. HTTP paths are under `/api`; health endpoints are unauthenticated and expose no evidence. JSON writes accept at most 256 KiB, including chunked input. The reverse proxy applies the same body limit.

| Operation | Authorization | Result |
| --- | --- | --- |
| GET /me | Any active credential | Tenant ID and role |
| POST /executions | ingestor or investigator | 201 new, 200 duplicate, 409 conflicting sanitized content |
| GET /executions | reader or investigator | Search by name, outcome filter, limit 1–100, bounded offset |
| GET /executions/{id} | reader or investigator | Full sanitized graph; 404 across tenant boundaries |
| GET /executions/{id}/export | reader or investigator | Downloadable JSON snapshot |
| GET /compare?left=&right= | reader or investigator | Occurrence-aligned differences and evidence span IDs |
| POST /replays | investigator | 202; requires Idempotency-Key of 8–100 characters |
| GET /replays | reader or investigator | Latest 50 jobs |
| GET /replays/{id} | reader or investigator | Request, lifecycle and result |
| POST /replays/{id}/cancel | investigator | Cancel queued/running; 409 absent/already terminal |
| GET /audit | investigator | Latest 100 tenant audit events |
| GET /metrics | investigator | Prometheus gauges for this tenant's evidence/jobs |

List pagination is offset based and may shift during concurrent inserts; it is an interactive browser mechanism, not a consistent export cursor. Export individual immutable executions for stable evidence. Replay lists and audit lists are bounded recent windows, not a complete archival query API.

## Evidence envelope

Schema version 1 requires a UUID id, bounded name/version, and 1–200 spans. Span IDs are local alphanumeric/underscore/hyphen identifiers. Exactly one span has no parent; every other parent must exist. Attributes accept only primitive string/integer/boolean values, up to 20 keys. Stored keys are restricted to http.method, http.route, messaging.system, messaging.destination, error.type, deployment.version, and db.operation. Values are not automatically classified for secrets. No HTTP headers, bodies, arbitrary tags, uploaded binaries, scripts, or destination URLs are supported.

The optional `fixture` is explicitly for checkout-v1: inventory_status, payment_status, captured_checkout_status, and quantity. An arbitrary imported trace without this fixture remains investigable but cannot be replayed. Fixtures are submitted evidence, not independently attested captures.

## Replay request and result

Request: execution_id, expected_status, optional inventory_status/payment_status overrides, and dependency_delay_ms from 0 to 1500. Schema rejects extra fields, including arbitrary commands and URLs. The result contains adapter version, observed/expected/captured status, `passed`, `matches_capture`, measured local elapsed_ms, dependency call evidence, and scope text. Elapsed time is a measurement of that one run, not a performance benchmark or guarantee.

Invalid input returns 422 without echoing submitted values. Missing/invalid/revoked credentials return 401; insufficient role returns 403. Tenant quotas return 429; database connection/statement failures return 503. Clients should retry ambiguous ingest/replay responses with the same identity/key. The runtime OpenAPI endpoint is public schema metadata, not a data endpoint.
