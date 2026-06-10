CREATE TABLE review_batches (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    candidate_run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    assertion_ids_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (candidate_run_id) REFERENCES candidate_extraction_runs (id)
);

CREATE TABLE standardization_candidates (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    review_batch_id TEXT NOT NULL,
    assertion_id TEXT NOT NULL,
    term_role TEXT NOT NULL,
    concept_type TEXT NOT NULL,
    original_text TEXT NOT NULL,
    suggested_concept_id TEXT,
    suggested_preferred_name TEXT,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    review_note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (review_batch_id) REFERENCES review_batches (id)
);

CREATE TABLE release_snapshots (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    release_id TEXT NOT NULL,
    published_object_uri TEXT NOT NULL,
    assertion_count INTEGER NOT NULL CHECK (assertion_count >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (release_id) REFERENCES graph_releases (id)
);

CREATE INDEX idx_review_batches_candidate_run
    ON review_batches (domain_id, candidate_run_id, created_at);

CREATE INDEX idx_standardization_candidates_batch
    ON standardization_candidates (domain_id, review_batch_id);

CREATE INDEX idx_release_snapshots_release
    ON release_snapshots (domain_id, release_id);
