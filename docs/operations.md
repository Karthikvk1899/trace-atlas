# Operations

## Start, health, and scaling

Run the README quickstart. Migration takes an advisory transaction lock so simultaneous migration commands serialize. The initial schema is version 1; upgrades beyond v1 do not exist yet. Readiness checks database access; liveness is independent. API/database errors are 503 and do not falsely acknowledge writes. `docker compose up -d --scale worker=2` runs competing workers without a central in-memory scheduler. More workers do not prove production scalability.

Inspect `docker compose logs --tail=100 api worker`. Worker logs omit request payloads. `/api/metrics` requires an investigator credential and exposes only that tenant's stored execution/job counts. Monitor PostgreSQL disk space, active/expired leases, failed jobs, API latency/503s and worker health using your deployment monitoring. No distributed tracing backend or hosted alerting is provisioned.

## Credentials

`docker compose exec api atlas tenant 'Team name'` provisions a tenant and prints its three credentials once. Keep output in a secret manager. The API cannot create privileged credentials. To revoke, hash the compromised token using SHA-256 locally and have the database operator set `credentials.revoked=true` for that digest with a parameterized query. Rotating credentials does not delete evidence. Store `.env` securely; never include it in screenshots or commits.

## Recovery

A worker that dies while running leaves a 30-second lease. Another worker can reclaim it; attempts are limited to three. Stale completion is rejected. Cancellation invalidates the lease but does not instantly terminate an already running fixed adapter. A database outage pauses progress and produces API 503 responses. Preserve execution IDs and replay idempotency keys when retrying after ambiguous responses.

`python3 scripts/operations_test.py` deliberately stops/restarts workers, the API and PostgreSQL in **this local Compose project**. It checks durable queued work, a completed replay after recovery, a 503 during database loss, and a logical backup restored into a uniquely named disposable database. It verifies a stored evidence digest, replay result and credential row presence, then drops only the disposable restore database. Do not run it against a shared/production stack.

## Backup and retention

Back up PostgreSQL with pg_dump and protect dumps like credentials: they contain evidence and credential digests. Restore into an isolated database, verify schema/evidence/results, and exercise reads before a planned cutover. CI's logical restore exercise is not a measured production RPO/RTO or proof of physical disaster recovery. PostgreSQL volume loss without an external backup loses all evidence and jobs.

There is no automatic deletion policy in v0.1. An operator must establish retention before long-running use. Preserve immutable evidence required by active jobs; replay snapshots are copied into jobs, but foreign-key deletion cascades jobs. Delete audit rows and terminal replay rows only under an explicit policy; deletion removes idempotency history. Tenant execution quota is enforced regardless of remaining disk. Audit is transactional application history, not a tamper-proof compliance log.

The Compose database has no published host port; API/UI bind loopback. Outside localhost, require TLS, separate migration/runtime database roles, backup encryption, network policy, resource/tenant quotas, log redaction, image assessment, and an incident procedure. No AWS configuration or cloud qualification is included.
