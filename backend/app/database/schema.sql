CREATE TABLE IF NOT EXISTS workspaces (
 id uuid PRIMARY KEY, owner uuid NOT NULL, revision integer NOT NULL DEFAULT 0,
 data_version integer NOT NULL DEFAULT 0, document jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS workspaces_owner ON workspaces(owner);
CREATE TABLE IF NOT EXISTS snapshots (
 workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 data_version integer NOT NULL, document jsonb NOT NULL,
 PRIMARY KEY(workspace_id,data_version)
);
CREATE TABLE IF NOT EXISTS uploads (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 owner uuid NOT NULL, name text NOT NULL, object_key text NOT NULL UNIQUE,
 expected_bytes bigint NOT NULL CHECK(expected_bytes BETWEEN 1 AND 15000000),
 state text NOT NULL DEFAULT 'pending', expires_at timestamptz NOT NULL DEFAULT now()+interval '2 hours',
 lease_until timestamptz, outcome jsonb, error text,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS uploads_workspace ON uploads(workspace_id);
CREATE TABLE IF NOT EXISTS findings (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 data_version integer NOT NULL, question text NOT NULL, result jsonb NOT NULL,
 pinned boolean NOT NULL DEFAULT false, created_at text NOT NULL, cache_key text NOT NULL
);
CREATE INDEX IF NOT EXISTS findings_history ON findings(workspace_id,data_version,created_at);
CREATE INDEX IF NOT EXISTS findings_cache ON findings(workspace_id,data_version,cache_key);
CREATE TABLE IF NOT EXISTS dashboards (
 workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 data_version integer NOT NULL, scope_key text NOT NULL, payload jsonb NOT NULL,
 PRIMARY KEY(workspace_id, data_version, scope_key)
);
CREATE TABLE IF NOT EXISTS request_limits (
 owner uuid PRIMARY KEY, window_start timestamptz NOT NULL, count integer NOT NULL
);
CREATE TABLE IF NOT EXISTS objects (
 object_key text PRIMARY KEY, owner uuid NOT NULL, workspace_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), delete_after timestamptz
);
-- Application tables are private to the backend's database role. Browser access is through FastAPI.
REVOKE ALL ON ALL TABLES IN SCHEMA analysis FROM PUBLIC;
