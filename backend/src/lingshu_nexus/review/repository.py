"""Review repository port and in-memory adapter."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from lingshu_domain import CanonicalConcept, EvidenceAssertion, GraphRelease, ReviewDecision
from lingshu_domain.validation import require_domain_id, require_text
from lingshu_nexus.persistence.models import AuditEvent
from lingshu_nexus.review.models import ReleaseRecord, ReviewBatch


class ReviewBatchNotFoundError(KeyError):
    """Raised when a review batch is unknown."""


class ReviewedAssertionNotFoundError(KeyError):
    """Raised when an assertion is unknown to the review repository."""


class ReleaseNotFoundError(KeyError):
    """Raised when a graph release is unknown."""


class ReviewRepository(Protocol):
    def add_concept(self, concept: CanonicalConcept) -> None:
        """Add or update one canonical concept known to review."""

    def list_concepts(self, *, domain_id: str) -> tuple[CanonicalConcept, ...]:
        """Return canonical concepts for one domain."""

    def add_batch(self, batch: ReviewBatch) -> None:
        """Persist a review batch."""

    def get_batch(self, *, domain_id: str, batch_id: str) -> ReviewBatch:
        """Return one review batch."""

    def list_batches(self, *, domain_id: str) -> tuple[ReviewBatch, ...]:
        """Return review batches for one domain."""

    def put_assertion(self, assertion: EvidenceAssertion) -> None:
        """Create or replace a reviewed assertion copy."""

    def get_assertion(self, *, domain_id: str, assertion_id: str) -> EvidenceAssertion:
        """Return a reviewed assertion copy."""

    def list_assertions(self, *, domain_id: str) -> tuple[EvidenceAssertion, ...]:
        """Return reviewed assertions for one domain."""

    def add_decision(self, decision: ReviewDecision) -> None:
        """Append an immutable review decision."""

    def decisions_for_assertion(
        self,
        *,
        domain_id: str,
        assertion_id: str,
    ) -> tuple[ReviewDecision, ...]:
        """Return review decisions for one assertion."""

    def latest_decision_for_assertion(
        self,
        *,
        domain_id: str,
        assertion_id: str,
    ) -> ReviewDecision | None:
        """Return the most recent decision for an assertion, if present."""

    def add_release_record(self, record: ReleaseRecord) -> None:
        """Persist one release snapshot."""

    def get_release_record(self, *, domain_id: str, release_id: str) -> ReleaseRecord:
        """Return one release snapshot."""

    def list_release_records(self, *, domain_id: str) -> tuple[ReleaseRecord, ...]:
        """Return releases for one domain."""

    def active_release_record(self, *, domain_id: str) -> ReleaseRecord | None:
        """Return the active release for a domain, if any."""

    def set_active_release(self, *, domain_id: str, release_id: str) -> GraphRelease:
        """Activate one release and deactivate other releases in the same domain."""

    def add_audit_event(self, event: AuditEvent) -> None:
        """Append an audit event."""

    def list_audit_events(self, *, domain_id: str) -> tuple[AuditEvent, ...]:
        """Return audit events for one domain."""


class InMemoryReviewRepository:
    def __init__(self) -> None:
        self._concepts: dict[tuple[str, str], CanonicalConcept] = {}
        self._batches: dict[tuple[str, str], ReviewBatch] = {}
        self._assertions: dict[tuple[str, str], EvidenceAssertion] = {}
        self._decisions: list[ReviewDecision] = []
        self._release_records: dict[tuple[str, str], ReleaseRecord] = {}
        self._audits: list[AuditEvent] = []

    def add_concept(self, concept: CanonicalConcept) -> None:
        self._concepts[(concept.domain_id, concept.id)] = concept

    def list_concepts(self, *, domain_id: str) -> tuple[CanonicalConcept, ...]:
        require_domain_id(domain_id)
        return tuple(
            sorted(
                (
                    concept
                    for (concept_domain_id, _), concept in self._concepts.items()
                    if concept_domain_id == domain_id
                ),
                key=lambda concept: (concept.type.value, concept.preferred_name),
            )
        )

    def add_batch(self, batch: ReviewBatch) -> None:
        identity = (batch.domain_id, batch.id)
        if identity in self._batches:
            raise ValueError(f"Review batch already exists: {identity}")
        self._batches[identity] = batch

    def get_batch(self, *, domain_id: str, batch_id: str) -> ReviewBatch:
        require_domain_id(domain_id)
        require_text(batch_id, "batch_id")
        try:
            return self._batches[(domain_id, batch_id)]
        except KeyError as exc:
            raise ReviewBatchNotFoundError(batch_id) from exc

    def list_batches(self, *, domain_id: str) -> tuple[ReviewBatch, ...]:
        require_domain_id(domain_id)
        batches = [
            batch
            for (batch_domain_id, _), batch in self._batches.items()
            if batch_domain_id == domain_id
        ]
        return tuple(sorted(batches, key=lambda batch: batch.created_at))

    def put_assertion(self, assertion: EvidenceAssertion) -> None:
        self._assertions[(assertion.domain_id, assertion.id)] = assertion

    def get_assertion(self, *, domain_id: str, assertion_id: str) -> EvidenceAssertion:
        require_domain_id(domain_id)
        require_text(assertion_id, "assertion_id")
        try:
            return self._assertions[(domain_id, assertion_id)]
        except KeyError as exc:
            raise ReviewedAssertionNotFoundError(assertion_id) from exc

    def list_assertions(self, *, domain_id: str) -> tuple[EvidenceAssertion, ...]:
        require_domain_id(domain_id)
        assertions = [
            assertion
            for (assertion_domain_id, _), assertion in self._assertions.items()
            if assertion_domain_id == domain_id
        ]
        return tuple(sorted(assertions, key=lambda assertion: assertion.id))

    def add_decision(self, decision: ReviewDecision) -> None:
        self._decisions.append(decision)

    def decisions_for_assertion(
        self,
        *,
        domain_id: str,
        assertion_id: str,
    ) -> tuple[ReviewDecision, ...]:
        require_domain_id(domain_id)
        require_text(assertion_id, "assertion_id")
        return tuple(
            decision
            for decision in self._decisions
            if decision.domain_id == domain_id and decision.assertion_id == assertion_id
        )

    def latest_decision_for_assertion(
        self,
        *,
        domain_id: str,
        assertion_id: str,
    ) -> ReviewDecision | None:
        decisions = self.decisions_for_assertion(domain_id=domain_id, assertion_id=assertion_id)
        if not decisions:
            return None
        return decisions[-1]

    def add_release_record(self, record: ReleaseRecord) -> None:
        identity = (record.release.domain_id, record.release.id)
        if identity in self._release_records:
            raise ValueError(f"Release already exists: {identity}")
        self._release_records[identity] = record

    def get_release_record(self, *, domain_id: str, release_id: str) -> ReleaseRecord:
        require_domain_id(domain_id)
        require_text(release_id, "release_id")
        try:
            return self._release_records[(domain_id, release_id)]
        except KeyError as exc:
            raise ReleaseNotFoundError(release_id) from exc

    def list_release_records(self, *, domain_id: str) -> tuple[ReleaseRecord, ...]:
        require_domain_id(domain_id)
        records = [
            record
            for (release_domain_id, _), record in self._release_records.items()
            if release_domain_id == domain_id
        ]
        return tuple(sorted(records, key=lambda record: record.created_at))

    def active_release_record(self, *, domain_id: str) -> ReleaseRecord | None:
        require_domain_id(domain_id)
        for (release_domain_id, _), record in self._release_records.items():
            if release_domain_id == domain_id and record.release.active:
                return record
        return None

    def set_active_release(self, *, domain_id: str, release_id: str) -> GraphRelease:
        require_domain_id(domain_id)
        require_text(release_id, "release_id")
        if (domain_id, release_id) not in self._release_records:
            raise ReleaseNotFoundError(release_id)
        activated: GraphRelease | None = None
        for identity, record in tuple(self._release_records.items()):
            release_domain_id, current_release_id = identity
            if release_domain_id != domain_id:
                continue
            active = current_release_id == release_id
            updated_release = replace(record.release, active=active)
            updated_record = ReleaseRecord(
                release=updated_release,
                assertions=record.assertions,
                artifact_ref=record.artifact_ref,
                created_at=record.created_at,
            )
            self._release_records[identity] = updated_record
            if active:
                activated = updated_release
        assert activated is not None
        return activated

    def add_audit_event(self, event: AuditEvent) -> None:
        self._audits.append(event)

    def list_audit_events(self, *, domain_id: str) -> tuple[AuditEvent, ...]:
        require_domain_id(domain_id)
        return tuple(event for event in self._audits if event.domain_id == domain_id)
