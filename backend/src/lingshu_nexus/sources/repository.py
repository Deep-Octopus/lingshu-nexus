"""SourceConnector repository port and in-memory adapter."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from lingshu_domain.validation import require_domain_id, require_text
from lingshu_nexus.sources.models import (
    SourceArtifactRecord,
    SourceConnectorConfig,
    SourceSyncRun,
)


class SourceConfigNotFoundError(KeyError):
    """Raised when a SourceConnector config is unknown."""


class SourceRunNotFoundError(KeyError):
    """Raised when a SourceConnector run is unknown."""


class SourceRepository(Protocol):
    def upsert_config(self, config: SourceConnectorConfig) -> None:
        """Create or replace a SourceConnector config."""

    def get_config(self, *, domain_id: str, source_id: str) -> SourceConnectorConfig:
        """Return one SourceConnector config."""

    def list_configs(self, *, domain_id: str) -> tuple[SourceConnectorConfig, ...]:
        """Return all SourceConnector configs for one domain."""

    def add_run(self, run: SourceSyncRun) -> None:
        """Persist one SourceConnector execution record."""

    def get_run(self, *, domain_id: str, run_id: str) -> SourceSyncRun:
        """Return one SourceConnector execution record."""

    def list_runs(self, *, domain_id: str) -> tuple[SourceSyncRun, ...]:
        """Return SourceConnector execution records for one domain."""

    def add_artifact_record(self, record: SourceArtifactRecord) -> None:
        """Persist one artifact processing record."""

    def list_artifact_records_for_run(
        self,
        *,
        domain_id: str,
        run_id: str,
    ) -> tuple[SourceArtifactRecord, ...]:
        """Return artifact records for one run."""

    def find_artifact_by_idempotency_key(
        self,
        *,
        domain_id: str,
        idempotency_key: str,
    ) -> SourceArtifactRecord | None:
        """Return an existing artifact record for the same idempotency key."""


class InMemorySourceRepository:
    def __init__(self) -> None:
        self._configs: dict[tuple[str, str], SourceConnectorConfig] = {}
        self._runs: dict[tuple[str, str], SourceSyncRun] = {}
        self._artifacts: dict[tuple[str, str], SourceArtifactRecord] = {}
        self._artifact_idempotency: dict[tuple[str, str], str] = {}

    def upsert_config(self, config: SourceConnectorConfig) -> None:
        self._configs[(config.domain_id, config.id)] = replace(config)

    def get_config(self, *, domain_id: str, source_id: str) -> SourceConnectorConfig:
        require_domain_id(domain_id)
        require_text(source_id, "source_id")
        try:
            return self._configs[(domain_id, source_id)]
        except KeyError as exc:
            raise SourceConfigNotFoundError(source_id) from exc

    def list_configs(self, *, domain_id: str) -> tuple[SourceConnectorConfig, ...]:
        require_domain_id(domain_id)
        configs = [
            config
            for (config_domain_id, _), config in self._configs.items()
            if config_domain_id == domain_id
        ]
        return tuple(sorted(configs, key=lambda config: (config.created_at, config.id)))

    def add_run(self, run: SourceSyncRun) -> None:
        identity = (run.domain_id, run.id)
        if identity in self._runs:
            raise ValueError(f"Source sync run already exists: {identity}")
        self._runs[identity] = run

    def get_run(self, *, domain_id: str, run_id: str) -> SourceSyncRun:
        require_domain_id(domain_id)
        require_text(run_id, "run_id")
        try:
            return self._runs[(domain_id, run_id)]
        except KeyError as exc:
            raise SourceRunNotFoundError(run_id) from exc

    def list_runs(self, *, domain_id: str) -> tuple[SourceSyncRun, ...]:
        require_domain_id(domain_id)
        runs = [run for (run_domain_id, _), run in self._runs.items() if run_domain_id == domain_id]
        return tuple(sorted(runs, key=lambda run: run.created_at))

    def add_artifact_record(self, record: SourceArtifactRecord) -> None:
        identity = (record.domain_id, record.id)
        if identity in self._artifacts:
            raise ValueError(f"Source artifact record already exists: {identity}")
        self._artifacts[identity] = record
        self._artifact_idempotency[(record.domain_id, record.idempotency_key)] = record.id

    def list_artifact_records_for_run(
        self,
        *,
        domain_id: str,
        run_id: str,
    ) -> tuple[SourceArtifactRecord, ...]:
        require_domain_id(domain_id)
        require_text(run_id, "run_id")
        records = [
            artifact
            for (artifact_domain_id, _), artifact in self._artifacts.items()
            if artifact_domain_id == domain_id and artifact.run_id == run_id
        ]
        return tuple(sorted(records, key=lambda artifact: artifact.created_at))

    def find_artifact_by_idempotency_key(
        self,
        *,
        domain_id: str,
        idempotency_key: str,
    ) -> SourceArtifactRecord | None:
        require_domain_id(domain_id)
        require_text(idempotency_key, "idempotency_key")
        artifact_id = self._artifact_idempotency.get((domain_id, idempotency_key))
        if artifact_id is None:
            return None
        return self._artifacts[(domain_id, artifact_id)]
