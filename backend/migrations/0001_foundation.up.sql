CREATE TABLE source_documents (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    file_version INTEGER NOT NULL CHECK (file_version >= 1),
    source_uri TEXT,
    doi TEXT,
    pmid TEXT,
    topic_tags_json TEXT NOT NULL DEFAULT '[]',
    license_note TEXT,
    source_quality_tier TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (domain_id, content_hash, file_version)
);

CREATE TABLE source_chunks (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    locator_json TEXT NOT NULL,
    text TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    embedding_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES source_documents (id)
);

CREATE TABLE studies (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    source_document_id TEXT NOT NULL,
    study_type TEXT NOT NULL DEFAULT 'unknown',
    publication_date TEXT,
    population_summary TEXT,
    risk_of_bias_status TEXT,
    journal_quartile TEXT,
    citation_count INTEGER,
    region_or_team TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_document_id) REFERENCES source_documents (id)
);

CREATE TABLE canonical_concepts (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    concept_type TEXT NOT NULL,
    preferred_name TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    external_code TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (domain_id, concept_type, preferred_name)
);

CREATE TABLE evidence_assertions (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    study_id TEXT,
    subject_json TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_json TEXT NOT NULL,
    population TEXT,
    parameter_set_json TEXT,
    outcome TEXT,
    direction TEXT NOT NULL DEFAULT 'unclear',
    source_chunk_ids_json TEXT NOT NULL,
    extraction_confidence REAL NOT NULL CHECK (
        extraction_confidence >= 0 AND extraction_confidence <= 1
    ),
    review_status TEXT NOT NULL DEFAULT 'pending',
    source_quality_signals_json TEXT NOT NULL DEFAULT '{}',
    valid_from TEXT,
    supersedes TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (study_id) REFERENCES studies (id)
);

CREATE TABLE review_decisions (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    assertion_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    decided_at TEXT NOT NULL,
    FOREIGN KEY (assertion_id) REFERENCES evidence_assertions (id)
);

CREATE TABLE graph_releases (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    version TEXT NOT NULL,
    included_assertion_ids_json TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    index_version TEXT NOT NULL,
    released_by TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (domain_id, version)
);

CREATE TABLE object_artifacts (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    layer TEXT NOT NULL,
    object_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    version INTEGER NOT NULL CHECK (version >= 1),
    storage_uri TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (domain_id, object_key, version)
);

CREATE TABLE graph_sync_records (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    release_id TEXT NOT NULL,
    graph_backend TEXT NOT NULL,
    status TEXT NOT NULL,
    synced_assertion_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (release_id) REFERENCES graph_releases (id)
);

CREATE TABLE job_runs (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    input_ref TEXT,
    output_ref TEXT,
    error TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

CREATE TABLE config_versions (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    config_type TEXT NOT NULL,
    version TEXT NOT NULL,
    checksum TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (domain_id, config_type, version)
);

CREATE TABLE audit_events (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

