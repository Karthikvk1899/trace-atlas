# Architecture and consistency

## Immutable evidence

An execution is a complete, single-root span graph, not a streaming partial trace. Validation rejects duplicate span IDs, missing parents, cycles, unknown fields, excessive spans, and oversized attributes. A fixed attribute allowlist is applied before hashing and persistence. SHA-256 identifies canonical sorted JSON; it is an integrity identifier, not a signature proving the producer's assertions are true.

The tenant comes exclusively from the hashed bearer credential lookup. Every object query carries tenant_id. The database composite primary key enforces isolation of identity namespaces, while application queries enforce access; PostgreSQL row-level security is not configured. Submission locks the tenant row to serialize the 10,000-execution quota. Same execution ID/same sanitized payload returns 200; different payload returns 409. First acceptance returns 201. An audit event commits in the same transaction.

Comparisons align service + operation + chronological occurrence. They show source span IDs and status/duration differences. Concurrent or structurally different requests may align imperfectly. The graph is observed parentage, not proof of a causal root cause or critical path. Relative timestamps are producer supplied and may contain clock skew; the console does not silently repair them.

## Replay lifecycle

Creation locks the tenant row, checks a 20-active-job quota, validates the supported fixture, and copies the immutable evidence into the job. Idempotency keys are tenant scoped and retained with the job. A duplicate key with a different normalized request returns 409. Job acceptance is durable before a worker sees it; PostgreSQL is the queue, so there is no database/broker dual-write gap.

Workers claim queued or expired running jobs using `FOR UPDATE SKIP LOCKED`. A claim increments attempts and writes a random fencing token and a 30-second database-clock lease. Work runs outside the claim transaction. Only a matching unexpired lease may commit a result. A crashed worker's lease can be reclaimed, up to three attempts; expired exhausted jobs become failed. Completed business assertions can be false while the job status remains completed. Infrastructure/adapter failures are separate failed jobs.

Cancellation atomically moves queued/running work to cancelled and clears the lease. A running subprocess may continue for its bounded lifetime, but cannot commit after cancellation. No production-side effects are possible through the fixed adapter. Shutdown allows the current bounded attempt to finish; a forced shutdown relies on lease expiry. Duplicate execution remains possible after a crash, and is safe only because this adapter has no external side effects. Do not reuse this queue as an exactly-once general-purpose task runner.

## Adapter boundary

The child runs only repository-owned Python code. It gets JSON status fixtures and numeric overrides through stdin, no database credentials and no inherited proxy configuration. Two localhost HTTP servers execute the bundled checkout behavior and dependency responses. Inventory failure maps to checkout 409; payment failure maps to 502; successful calls map to 201. A synthetic delay applies to each dependency response. Captured quantity is passed in the request; this demo does not model real inventory quantities or payment accounting.

The process has CPU/address-space/file-descriptor limits and a 12-second parent timeout. Compose adds a read-only filesystem, dropped capabilities, memory/CPU ceilings, and an internal network. This is a fixed-adapter security boundary, not a hardened sandbox for arbitrary hostile code. The worker process retains database access; extensibility would require a stronger runner isolation design.
