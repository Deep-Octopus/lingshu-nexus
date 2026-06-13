CREATE TABLE source_connector_configs (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    name TEXT NOT NULL,
    connector_type TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    schedule_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE source_sync_runs (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    status TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    retried_from_run_id TEXT,
    window_start TEXT,
    window_end TEXT,
    cursor TEXT,
    raw_response_object_uri TEXT,
    artifact_ids_json TEXT NOT NULL DEFAULT '[]',
    document_ids_json TEXT NOT NULL DEFAULT '[]',
    candidate_run_ids_json TEXT NOT NULL DEFAULT '[]',
    review_batch_ids_json TEXT NOT NULL DEFAULT '[]',
    duplicate_count INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
    failed_artifact_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_artifact_count >= 0),
    impact_summary_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES source_connector_configs (id),
    FOREIGN KEY (retried_from_run_id) REFERENCES source_sync_runs (id)
);

CREATE TABLE source_artifact_records (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    raw_object_uri TEXT,
    external_id TEXT,
    filename TEXT,
    source_uri TEXT,
    document_id TEXT,
    candidate_run_id TEXT,
    review_batch_id TEXT,
    message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES source_connector_configs (id),
    FOREIGN KEY (run_id) REFERENCES source_sync_runs (id),
    FOREIGN KEY (document_id) REFERENCES source_documents (id),
    FOREIGN KEY (candidate_run_id) REFERENCES candidate_extraction_runs (id),
    UNIQUE (domain_id, idempotency_key)
);

CREATE INDEX idx_source_connector_configs_domain
    ON source_connector_configs (domain_id, connector_type, enabled);

CREATE INDEX idx_source_sync_runs_source
    ON source_sync_runs (domain_id, source_id, created_at);

CREATE INDEX idx_source_artifact_records_run
    ON source_artifact_records (domain_id, run_id, created_at);
