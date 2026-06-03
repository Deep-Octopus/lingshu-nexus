# Backend Migrations

Migration files are paired as `<version>.up.sql` and `<version>.down.sql`.

T-020 uses a conservative SQL subset so the foundation migration can be
smoke-tested with SQLite while preserving the PostgreSQL target selected for the
project. PostgreSQL-specific JSONB, vector indexes, and Alembic integration are
deferred until later tasks need them.

