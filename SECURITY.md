# Security policy and threat model

Report vulnerabilities privately using GitHub private vulnerability reporting when enabled. Do not put real credentials, private traces, or customer data in public issues. This is a reference release, not a production-qualified hosted product.

## Protected assets and trust boundaries

Evidence, replay fixtures/results, tenant credentials, and audit history are protected assets. Producers, browser input, imported files, and MCP consumers are untrusted. The database and operator with access to its credentials are trusted. The MCP host/model provider is a separate trust boundary: read permission to a tenant permits disclosure of that tenant's evidence to the configured assistant. Evidence can contain prompt injection; never treat it as instructions or use it to authorize tools or shell commands.

Credentials contain 256 random bits; only SHA-256 digests are stored. Roles are reader, ingestor, and investigator. Credentials are long-lived, manually provisioned and manually revoked by a database operator. OIDC, MFA, token expiry, invitations, and per-document ACLs are not implemented. The browser keeps credentials in memory. A compromised same-origin script can still read them. TLS is mandatory outside localhost.

All object access is tenant scoped; tests exercise read, compare, replay, audit and role boundaries. Database access is not isolated by separate per-tenant roles/RLS. An application SQL bug or compromised operator can cross tenants. The shared PostgreSQL owner account in Compose is development infrastructure, not a production least-privilege role model.

## Input, replay and resource controls

Requests are body limited before parsing; graphs and attributes have explicit bounds. Arbitrary headers and payload bodies are absent from the schema. Unknown attribute keys are dropped before hashing and storage. **Names, operation strings and allowlisted values can still contain secrets or personal information.** Producers must sanitize them before transmission. This is not a comprehensive DLP system. Validation responses omit input values; API access logs are disabled to avoid logging queries and identifiers.

SQL uses bound parameters. The UI renders trace values as text, never HTML. The proxy sets CSP, frame denial, nosniff and referrer policy. Inline styles are allowed for dynamic timeline geometry; inline scripts are not. APIs accept bearer headers, not cookie sessions, and do not enable cross-origin access.

Replay accepts no code, command, filesystem path, hostname, or credentials. Only the fixed checkout adapter runs. It connects exclusively to generated loopback HTTP servers. Internal Compose networking denies ordinary external network egress. Subprocess, container and request limits reduce resource abuse, but this is not an arbitrary-code sandbox. The parent worker can reach PostgreSQL. No public exposure should be attempted without stronger infrastructure controls and assessment.

Tenant limits are 10,000 execution snapshots and 20 active replay jobs. Completed jobs and audit rows have no automatic retention. Aggregate multi-tenant storage, admission rate limits, fair scheduling, audit tamper resistance, and abuse prevention need additional deployment controls. Never expose the local stack as a public service.

## Verification boundaries

CI includes CodeQL, Python/npm advisory audits, authorization/concurrency tests, real HTTP replay, and container integration. These checks do not establish absence of vulnerabilities. OS/container-image scanning, external penetration testing, cloud network controls, production restore objectives, cryptographic evidence signing, and disaster recovery remain unqualified. Base images use maintained version tags rather than immutable digests; resolve and assess images for your own deployment.
