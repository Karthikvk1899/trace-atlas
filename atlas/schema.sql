CREATE TABLE IF NOT EXISTS schema_version (version integer PRIMARY KEY);
INSERT INTO schema_version VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS tenants (id uuid PRIMARY KEY, name text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS credentials (
 digest text PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenants(id), role text NOT NULL CHECK(role IN ('reader','investigator','ingestor')), revoked boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS executions (
 tenant_id uuid NOT NULL REFERENCES tenants(id), id uuid NOT NULL, name text NOT NULL, outcome text NOT NULL,
 version text NOT NULL, digest text NOT NULL, evidence jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS executions_recent ON executions(tenant_id,created_at DESC,id);
CREATE TABLE IF NOT EXISTS replays (
 tenant_id uuid NOT NULL, id uuid NOT NULL, execution_id uuid NOT NULL, idempotency_key text NOT NULL,
 request_digest text NOT NULL, request jsonb NOT NULL, evidence jsonb NOT NULL,
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','failed','cancelled')),
 attempts integer NOT NULL DEFAULT 0, lease_token uuid, lease_until timestamptz, result jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id), UNIQUE(tenant_id,idempotency_key),
 FOREIGN KEY(tenant_id,execution_id) REFERENCES executions(tenant_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS replay_claim ON replays(status,lease_until,created_at);
CREATE TABLE IF NOT EXISTS audit (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenants(id),
 action text NOT NULL, resource_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
