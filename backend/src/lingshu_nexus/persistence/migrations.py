"""Migration file loader for SQL migration smoke tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[3]
MIGRATION_DIR = BACKEND_DIR / "migrations"


@dataclass(frozen=True)
class MigrationPair:
    name: str
    up_sql: str
    down_sql: str


def load_migration_pair(name: str) -> MigrationPair:
    up_path = MIGRATION_DIR / f"{name}.up.sql"
    down_path = MIGRATION_DIR / f"{name}.down.sql"
    if not up_path.exists() or not down_path.exists():
        raise FileNotFoundError(f"Migration pair not found: {name}")
    return MigrationPair(
        name=name,
        up_sql=up_path.read_text(encoding="utf-8"),
        down_sql=down_path.read_text(encoding="utf-8"),
    )
