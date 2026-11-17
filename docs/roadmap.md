# Scope and roadmap

The first release proves one vertical workflow: complete normalized evidence → investigation → comparison → bounded real HTTP experiment → durable result. It is independently useful for contract-based investigations, but its replay adapter is intentionally narrow.

Potential next milestones, **not implemented**:

1. Native OTLP HTTP/JSON intake with partial-trace assembly, late-span watermarks, explicit clock-skew handling and provenance.
2. Instrumented FastAPI/Spring Boot example services and an adapter SDK with conformance tests.
3. Strongly isolated runners with explicit network capabilities, immutable application images, and external effects disabled by construction.
4. S3-compatible artifact storage, signed evidence manifests, retention/garbage collection, and large-trace query indexing.
5. OIDC/SSO, expiring scoped credentials, collaborative investigations, saved assertions and CI regression gates.
6. Load/capacity experiments, multi-node recovery qualification, deployment automation and independently reviewed security boundaries.

An AI-generated explanation would require evidence citations and explicit uncertainty. It must not be described as an automatic root-cause oracle. No LLM integration is required for the current deterministic comparison or MCP tools.

Feature count, repository size, and passing CI are not substitutes for adoption, reliability evidence, or maintenance. Broader format support should arrive only with tests and precise failure behavior.
