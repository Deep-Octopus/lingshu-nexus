# Backend Migrations

Migration files are paired as `<version>.up.sql` and `<version>.down.sql`.

T-020 uses a conservative SQL subset so the foundation migration can be
smoke-tested with SQLite while preserving the PostgreSQL target selected for the
project. PostgreSQL-specific JSONB, vector indexes, and Alembic integration are
deferred until later tasks need them.

T-030 adds `0002_document_ingestion` for upload/parser status metadata. The
runtime service currently uses an in-memory document repository plus immutable
object-store adapters; the migration records the table shape expected when the
document repository is moved to PostgreSQL.

T-040 adds `0003_candidate_extraction` for provider/model/prompt/schema metadata
and candidate EvidenceAssertion records. Candidate data remains separate from
published graph data and must pass later review before release.

T-050 adds `0004_review_release` for review batches, standardization candidates,
and immutable release snapshots. Existing candidate rows are not overwritten when
review decisions or published release artifacts are created.
