CREATE TABLE skill_registry_entries (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    scope TEXT NOT NULL,
    minimum_role TEXT NOT NULL,
    server_allowed_tools_json TEXT NOT NULL DEFAULT '[]',
    supported_query_types_json TEXT NOT NULL DEFAULT '[]',
    checksum TEXT NOT NULL,
    source_path TEXT NOT NULL,
    test_cases_path TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (domain_id, skill_id, version)
);

CREATE TABLE skill_execution_logs (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    skill_version TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    route_mode TEXT NOT NULL,
    query_text TEXT NOT NULL,
    query_type TEXT NOT NULL,
    status TEXT NOT NULL,
    release_id TEXT,
    release_version TEXT,
    citation_keys_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    elapsed_ms INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (release_id) REFERENCES graph_releases (id)
);

CREATE INDEX idx_skill_registry_domain_status
    ON skill_registry_entries (domain_id, status, scope);

CREATE INDEX idx_skill_execution_logs_domain_skill
    ON skill_execution_logs (domain_id, skill_id, created_at);

CREATE INDEX idx_skill_execution_logs_release
    ON skill_execution_logs (domain_id, release_id);
