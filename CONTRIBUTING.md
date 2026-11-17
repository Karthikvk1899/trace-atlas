# Contributing

Use Python 3.12 and Node 24. Install the locked runtime first, then `pip install -e '.[test]'` and `npm ci --prefix ui`. Run Ruff, pytest, frontend tests/build, dependency audits, and the Docker integration before proposing a behavior change. Generate contracts using `python scripts/contracts.py` when API/schema changes.

Keep changes small and explain the observed problem, new behavior, and verification. Add regression coverage for a real failure mode. Never commit credentials, real customer traces, database dumps, or LinkedIn drafts. Tests must use disposable tenants. New replay adapters must not execute uploaded code or accept unrestricted network destinations; propose the isolation and contract design before implementation.

Open bug reports with the revision, reproduction using synthetic evidence, expected/actual outcome and sanitized logs. Report security issues privately as described in SECURITY.md. No production-readiness claims based only on CI.
