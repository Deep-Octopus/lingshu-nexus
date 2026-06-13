"""Review workflow and graph release use cases."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import uuid4

from lingshu_domain import (
    ACUPUNCTURE_DOMAIN,
    ConceptType,
    EvidenceAssertion,
    EvidenceTerm,
    GraphRelease,
    ParameterSet,
    ReviewDecision,
    ReviewDecisionKind,
    ReviewStatus,
    SourceChunk,
    SourceQualitySignals,
)
from lingshu_domain.validation import SchemaValidationError, require_domain_id, require_text
from lingshu_nexus.extraction.models import CandidateExtractionRun
from lingshu_nexus.persistence.models import AuditEvent, DataLayer, JobStatus
from lingshu_nexus.persistence.object_store import ObjectRef, ObjectStore
from lingshu_nexus.review.models import (
    NormalizationStatus,
    ReleasePreview,
    ReleasePreviewExclusion,
    ReleaseRecord,
    ReviewBatch,
    StandardizationCandidate,
    utcnow,
)
from lingshu_nexus.review.normalization import ConceptNormalizer
from lingshu_nexus.review.repository import ReviewRepository


class ReviewWorkflowError(ValueError):
    """Raised when a review action violates the workflow."""


class ReleaseValidationError(ValueError):
    """Raised when a release request is not publishable."""


class ReviewReleaseService:
    def __init__(
        self,
        *,
        repository: ReviewRepository,
        object_store: ObjectStore,
        normalizer: ConceptNormalizer,
        schema_version: str = ACUPUNCTURE_DOMAIN.schema_version,
        index_version: str = "graph-release-v0.1",
    ) -> None:
        self._repository = repository
        self._object_store = object_store
        self._normalizer = normalizer
        self._schema_version = schema_version
        self._index_version = index_version
        for concept in normalizer.concepts(domain_id=ACUPUNCTURE_DOMAIN.domain_id):
            self._repository.add_concept(concept)

    def create_review_batch(
        self,
        *,
        run: CandidateExtractionRun,
        source_chunks: tuple[SourceChunk, ...] = (),
        created_by: str = "system",
    ) -> ReviewBatch:
        require_text(created_by, "created_by")
        if run.status is not JobStatus.SUCCEEDED:
            raise ReviewWorkflowError("Only succeeded candidate extraction runs can be reviewed")
        if not run.evidence_assertions:
            raise ReviewWorkflowError("Candidate extraction run has no evidence assertions")
        if any(chunk.domain_id != run.domain_id for chunk in source_chunks):
            raise ReviewWorkflowError("Source chunk domain_id must match candidate run domain_id")

        batch_id = f"review_batch_{uuid4().hex}"
        chunk_parser_versions = {chunk.id: chunk.parser_version for chunk in source_chunks}
        assertions: list[EvidenceAssertion] = []
        candidates: list[StandardizationCandidate] = []
        for assertion in run.evidence_assertions:
            if assertion.domain_id != run.domain_id:
                raise ReviewWorkflowError(
                    "EvidenceAssertion domain_id must match candidate run domain_id"
                )
            standardized, assertion_candidates = self._standardize_assertion(
                assertion=assertion,
                review_batch_id=batch_id,
                chunk_parser_versions=chunk_parser_versions,
                run=run,
            )
            assertions.append(standardized)
            candidates.extend(assertion_candidates)
            self._repository.put_assertion(standardized)

        batch = ReviewBatch(
            id=batch_id,
            domain_id=run.domain_id,
            candidate_run_id=run.id,
            assertion_ids=tuple(assertion.id for assertion in assertions),
            normalization_candidates=tuple(candidates),
            created_by=created_by,
        )
        self._repository.add_batch(batch)
        self._audit(
            domain_id=run.domain_id,
            actor_id=created_by,
            action="review_batch.created",
            target_type="review_batch",
            target_id=batch.id,
            metadata={"candidate_run_id": run.id, "assertion_count": len(assertions)},
        )
        return batch

    def approve_assertion(
        self,
        *,
        domain_id: str,
        assertion_id: str,
        reviewer: str,
        reason: str,
        actor_role: str | None = None,
    ) -> EvidenceAssertion:
        return self._decide_assertion(
            domain_id=domain_id,
            assertion_id=assertion_id,
            reviewer=reviewer,
            reason=reason,
            decision=ReviewDecisionKind.APPROVE,
            status=ReviewStatus.APPROVED,
            actor_role=actor_role,
        )

    def reject_assertion(
        self,
        *,
        domain_id: str,
        assertion_id: str,
        reviewer: str,
        reason: str,
        actor_role: str | None = None,
    ) -> EvidenceAssertion:
        return self._decide_assertion(
            domain_id=domain_id,
            assertion_id=assertion_id,
            reviewer=reviewer,
            reason=reason,
            decision=ReviewDecisionKind.REJECT,
            status=ReviewStatus.REJECTED,
            actor_role=actor_role,
        )

    def modify_assertion(
        self,
        *,
        domain_id: str,
        assertion_id: str,
        reviewer: str,
        reason: str,
        subject_text: str | None = None,
        subject_concept_id: str | None = None,
        object_text: str | None = None,
        object_concept_id: str | None = None,
        population: str | None = None,
        outcome: str | None = None,
        metadata_updates: dict[str, Any] | None = None,
        approve: bool = True,
        actor_role: str | None = None,
    ) -> EvidenceAssertion:
        assertion = self._repository.get_assertion(domain_id=domain_id, assertion_id=assertion_id)
        metadata = dict(assertion.metadata)
        if metadata_updates:
            metadata.update(metadata_updates)
        updated = replace(
            assertion,
            subject=_replace_term(
                assertion.subject,
                text=subject_text,
                concept_id=subject_concept_id,
            ),
            object=_replace_term(
                assertion.object,
                text=object_text,
                concept_id=object_concept_id,
            ),
            population=population if population is not None else assertion.population,
            outcome=outcome if outcome is not None else assertion.outcome,
            metadata=metadata,
            review_status=ReviewStatus.APPROVED if approve else ReviewStatus.NEEDS_REVISION,
        )
        return self._record_decision(
            before=assertion,
            after=updated,
            reviewer=reviewer,
            reason=reason,
            decision=ReviewDecisionKind.MODIFY,
            actor_role=actor_role,
        )

    def mark_conflict(
        self,
        *,
        domain_id: str,
        assertion_id: str,
        reviewer: str,
        reason: str,
        conflict_with_assertion_ids: tuple[str, ...],
        actor_role: str | None = None,
    ) -> EvidenceAssertion:
        if not conflict_with_assertion_ids:
            raise ReviewWorkflowError("conflict_with_assertion_ids must not be empty")
        assertion = self._repository.get_assertion(domain_id=domain_id, assertion_id=assertion_id)
        for conflict_id in conflict_with_assertion_ids:
            self._repository.get_assertion(domain_id=domain_id, assertion_id=conflict_id)
        metadata = dict(assertion.metadata)
        metadata["conflict"] = {
            "status": "conflict",
            "with_assertion_ids": list(conflict_with_assertion_ids),
            "note": reason,
        }
        updated = replace(assertion, review_status=ReviewStatus.CONFLICT, metadata=metadata)
        return self._record_decision(
            before=assertion,
            after=updated,
            reviewer=reviewer,
            reason=reason,
            decision=ReviewDecisionKind.MARK_CONFLICT,
            actor_role=actor_role,
        )

    def preview_release(
        self,
        *,
        domain_id: str,
        assertion_ids: tuple[str, ...],
    ) -> ReleasePreview:
        require_domain_id(domain_id)
        active = self._repository.active_release_record(domain_id=domain_id)
        active_ids = set(active.release.included_assertion_ids) if active else set()
        included: list[str] = []
        excluded: list[ReleasePreviewExclusion] = []
        conflict_ids: list[str] = []
        for assertion_id in assertion_ids:
            try:
                assertion = self._repository.get_assertion(
                    domain_id=domain_id,
                    assertion_id=assertion_id,
                )
            except KeyError:
                excluded.append(
                    ReleasePreviewExclusion(assertion_id=assertion_id, reason="not_found")
                )
                continue
            if assertion.review_status not in {ReviewStatus.APPROVED, ReviewStatus.CONFLICT}:
                excluded.append(
                    ReleasePreviewExclusion(
                        assertion_id=assertion_id,
                        reason=f"review_status:{assertion.review_status.value}",
                    )
                )
                continue
            included.append(assertion_id)
            if assertion.review_status is ReviewStatus.CONFLICT:
                conflict_ids.append(assertion_id)
        included_set = set(included)
        return ReleasePreview(
            domain_id=domain_id,
            requested_assertion_ids=assertion_ids,
            included_assertion_ids=tuple(included),
            excluded_assertions=tuple(excluded),
            additions=tuple(
                assertion_id for assertion_id in included if assertion_id not in active_ids
            ),
            removals=tuple(
                assertion_id for assertion_id in active_ids if assertion_id not in included_set
            ),
            unchanged=tuple(
                assertion_id for assertion_id in included if assertion_id in active_ids
            ),
            conflict_assertion_ids=tuple(conflict_ids),
            active_release_id=active.release.id if active else None,
        )

    def create_release(
        self,
        *,
        domain_id: str,
        version: str,
        assertion_ids: tuple[str, ...],
        released_by: str,
        actor_role: str | None = None,
    ) -> ReleaseRecord:
        require_domain_id(domain_id)
        require_text(version, "version")
        require_text(released_by, "released_by")
        assertions = tuple(
            self._repository.get_assertion(domain_id=domain_id, assertion_id=assertion_id)
            for assertion_id in assertion_ids
        )
        if not assertions:
            raise ReleaseValidationError("Release must include at least one assertion")
        for assertion in assertions:
            self._validate_release_assertion(assertion)

        release = GraphRelease(
            id=f"release_{uuid4().hex}",
            domain_id=domain_id,
            version=version,
            included_assertion_ids=tuple(assertion.id for assertion in assertions),
            schema_version=self._schema_version,
            index_version=self._index_version,
            released_by=released_by,
            active=False,
        )
        artifact_ref = self._store_release_artifact(release=release, assertions=assertions)
        record = ReleaseRecord(release=release, assertions=assertions, artifact_ref=artifact_ref)
        self._repository.add_release_record(record)
        self._audit(
            domain_id=domain_id,
            actor_id=released_by,
            action="release.created",
            target_type="graph_release",
            target_id=release.id,
            metadata={
                "version": version,
                "assertion_count": len(assertions),
                "actor_role": actor_role,
            },
        )
        return record

    def activate_release(
        self,
        *,
        domain_id: str,
        release_id: str,
        actor_id: str,
        actor_role: str | None = None,
    ) -> GraphRelease:
        require_text(actor_id, "actor_id")
        release = self._repository.set_active_release(domain_id=domain_id, release_id=release_id)
        self._audit(
            domain_id=domain_id,
            actor_id=actor_id,
            action="release.activated",
            target_type="graph_release",
            target_id=release_id,
            metadata={"version": release.version, "actor_role": actor_role},
        )
        return release

    def rollback_to_release(
        self,
        *,
        domain_id: str,
        release_id: str,
        actor_id: str,
        reason: str,
        actor_role: str | None = None,
    ) -> GraphRelease:
        require_text(reason, "reason")
        release = self._repository.set_active_release(domain_id=domain_id, release_id=release_id)
        self._audit(
            domain_id=domain_id,
            actor_id=actor_id,
            action="release.rollback",
            target_type="graph_release",
            target_id=release_id,
            metadata={"version": release.version, "reason": reason, "actor_role": actor_role},
        )
        return release

    def list_releases(self, *, domain_id: str) -> tuple[ReleaseRecord, ...]:
        return self._repository.list_release_records(domain_id=domain_id)

    def active_release(self, *, domain_id: str) -> ReleaseRecord | None:
        return self._repository.active_release_record(domain_id=domain_id)

    def record_audit_event(
        self,
        *,
        domain_id: str,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._audit(
            domain_id=domain_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata=metadata or {},
        )

    def list_audit_events(self, *, domain_id: str) -> tuple[AuditEvent, ...]:
        return self._repository.list_audit_events(domain_id=domain_id)

    def list_review_batches(self, *, domain_id: str) -> tuple[ReviewBatch, ...]:
        return self._repository.list_batches(domain_id=domain_id)

    def get_review_batch(self, *, domain_id: str, batch_id: str) -> ReviewBatch:
        return self._repository.get_batch(domain_id=domain_id, batch_id=batch_id)

    def list_assertions(self, *, domain_id: str) -> tuple[EvidenceAssertion, ...]:
        return self._repository.list_assertions(domain_id=domain_id)

    def get_assertion(self, *, domain_id: str, assertion_id: str) -> EvidenceAssertion:
        return self._repository.get_assertion(domain_id=domain_id, assertion_id=assertion_id)

    def _standardize_assertion(
        self,
        *,
        assertion: EvidenceAssertion,
        review_batch_id: str,
        chunk_parser_versions: dict[str, str],
        run: CandidateExtractionRun,
    ) -> tuple[EvidenceAssertion, tuple[StandardizationCandidate, ...]]:
        candidates = [
            self._normalizer.candidate_for_term(
                domain_id=assertion.domain_id,
                review_batch_id=review_batch_id,
                assertion_id=assertion.id,
                term_role="subject",
                term=assertion.subject,
            ),
            self._normalizer.candidate_for_term(
                domain_id=assertion.domain_id,
                review_batch_id=review_batch_id,
                assertion_id=assertion.id,
                term_role="object",
                term=assertion.object,
            ),
        ]
        parameter_set = assertion.parameter_set
        if parameter_set and parameter_set.stimulation_site:
            candidates.append(
                self._normalizer.candidate_for_term(
                    domain_id=assertion.domain_id,
                    review_batch_id=review_batch_id,
                    assertion_id=assertion.id,
                    term_role="parameter_set.stimulation_site",
                    term=EvidenceTerm(
                        type=ConceptType.STIMULATION_SITE,
                        text=parameter_set.stimulation_site,
                    ),
                )
            )

        subject = _apply_term_candidate(assertion.subject, candidates[0])
        object_term = _apply_term_candidate(assertion.object, candidates[1])
        parameter_set = _apply_parameter_set_candidate(parameter_set, candidates)
        parser_versions = _parser_versions_for_assertion(
            assertion=assertion,
            chunk_parser_versions=chunk_parser_versions,
        )
        metadata = dict(assertion.metadata)
        metadata["lineage"] = {
            "candidate_run_id": run.id,
            "provider": run.provider,
            "model": run.model,
            "prompt_version": run.prompt_version,
            "schema_version": run.schema_version,
            "parser_versions": parser_versions,
        }
        metadata["normalization_candidates"] = [
            _normalization_candidate_to_json(candidate) for candidate in candidates
        ]
        standardized = replace(
            assertion,
            subject=subject,
            object=object_term,
            parameter_set=parameter_set,
            review_status=ReviewStatus.PENDING,
            metadata=metadata,
        )
        return standardized, tuple(candidates)

    def _decide_assertion(
        self,
        *,
        domain_id: str,
        assertion_id: str,
        reviewer: str,
        reason: str,
        decision: ReviewDecisionKind,
        status: ReviewStatus,
        actor_role: str | None,
    ) -> EvidenceAssertion:
        assertion = self._repository.get_assertion(domain_id=domain_id, assertion_id=assertion_id)
        updated = replace(assertion, review_status=status)
        return self._record_decision(
            before=assertion,
            after=updated,
            reviewer=reviewer,
            reason=reason,
            decision=decision,
            actor_role=actor_role,
        )

    def _record_decision(
        self,
        *,
        before: EvidenceAssertion,
        after: EvidenceAssertion,
        reviewer: str,
        reason: str,
        decision: ReviewDecisionKind,
        actor_role: str | None = None,
    ) -> EvidenceAssertion:
        require_text(reviewer, "reviewer")
        require_text(reason, "reason")
        self._repository.put_assertion(after)
        review_decision = ReviewDecision(
            id=f"decision_{uuid4().hex}",
            domain_id=after.domain_id,
            assertion_id=after.id,
            reviewer=reviewer,
            decision=decision,
            reason=reason,
            timestamp=utcnow(),
            before=_assertion_to_json(before),
            after=_assertion_to_json(after),
        )
        self._repository.add_decision(review_decision)
        self._audit(
            domain_id=after.domain_id,
            actor_id=reviewer,
            action=f"assertion.{decision.value}",
            target_type="evidence_assertion",
            target_id=after.id,
            metadata={"review_status": after.review_status.value, "actor_role": actor_role},
        )
        return after

    def _validate_release_assertion(self, assertion: EvidenceAssertion) -> None:
        try:
            assertion.validate_publishable()
        except SchemaValidationError as exc:
            raise ReleaseValidationError(str(exc)) from exc
        decision = self._repository.latest_decision_for_assertion(
            domain_id=assertion.domain_id,
            assertion_id=assertion.id,
        )
        if decision is None:
            raise ReleaseValidationError(f"Assertion has no review decision: {assertion.id}")
        if decision.decision not in {
            ReviewDecisionKind.APPROVE,
            ReviewDecisionKind.MODIFY,
            ReviewDecisionKind.MARK_CONFLICT,
        }:
            raise ReleaseValidationError(
                f"Assertion latest review decision is not publishable: {assertion.id}"
            )
        lineage = assertion.metadata.get("lineage")
        if not isinstance(lineage, dict):
            raise ReleaseValidationError(f"Assertion has no extraction lineage: {assertion.id}")
        required = ("candidate_run_id", "provider", "model", "prompt_version", "schema_version")
        missing = [field for field in required if not lineage.get(field)]
        parser_versions = lineage.get("parser_versions")
        if not parser_versions:
            missing.append("parser_versions")
        if missing:
            raise ReleaseValidationError(
                f"Assertion release lineage is incomplete for {assertion.id}: {missing}"
            )

    def _store_release_artifact(
        self,
        *,
        release: GraphRelease,
        assertions: tuple[EvidenceAssertion, ...],
    ) -> ObjectRef:
        artifact = {
            "release": _release_to_json(release),
            "assertions": [_assertion_to_json(assertion) for assertion in assertions],
            "created_at": utcnow(),
        }
        return self._object_store.put(
            domain_id=release.domain_id,
            object_key=f"releases/{release.id}.json",
            content=json.dumps(artifact, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            layer=DataLayer.PUBLISHED,
            media_type="application/json",
            version=1,
        )

    def _audit(
        self,
        *,
        domain_id: str,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        metadata: dict[str, Any],
    ) -> None:
        self._repository.add_audit_event(
            AuditEvent(
                id=f"audit_{uuid4().hex}",
                domain_id=domain_id,
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                metadata=metadata,
            )
        )


def _replace_term(
    term: EvidenceTerm,
    *,
    text: str | None = None,
    concept_id: str | None = None,
) -> EvidenceTerm:
    original_text = term.original_text or term.text
    return EvidenceTerm(
        type=term.type,
        text=text if text is not None else term.text,
        concept_id=concept_id if concept_id is not None else term.concept_id,
        original_text=original_text,
    )


def _apply_term_candidate(
    term: EvidenceTerm,
    candidate: StandardizationCandidate,
) -> EvidenceTerm:
    if (
        candidate.status is NormalizationStatus.SUGGESTED
        and candidate.suggested_concept_id
        and candidate.suggested_preferred_name
    ):
        return EvidenceTerm(
            type=term.type,
            text=candidate.suggested_preferred_name,
            concept_id=candidate.suggested_concept_id,
            original_text=term.original_text or term.text,
        )
    if candidate.status is NormalizationStatus.NEEDS_REVIEW:
        return EvidenceTerm(
            type=term.type,
            text=term.original_text or term.text,
            concept_id=None,
            original_text=term.original_text or term.text,
        )
    return EvidenceTerm(
        type=term.type,
        text=term.text,
        concept_id=term.concept_id,
        original_text=term.original_text or term.text,
    )


def _apply_parameter_set_candidate(
    parameter_set: ParameterSet | None,
    candidates: list[StandardizationCandidate],
) -> ParameterSet | None:
    if parameter_set is None:
        return None
    site_candidate = next(
        (
            candidate
            for candidate in candidates
            if candidate.term_role == "parameter_set.stimulation_site"
        ),
        None,
    )
    if (
        site_candidate is None
        or site_candidate.status is not NormalizationStatus.SUGGESTED
        or not site_candidate.suggested_preferred_name
    ):
        return parameter_set
    return ParameterSet(
        stimulation_site=site_candidate.suggested_preferred_name,
        frequency_hz=parameter_set.frequency_hz,
        pulse_width_us=parameter_set.pulse_width_us,
        intensity=parameter_set.intensity,
        duration_minutes=parameter_set.duration_minutes,
        course=parameter_set.course,
        waveform=parameter_set.waveform,
        dose=parameter_set.dose,
        sham_control=parameter_set.sham_control,
        raw_text=parameter_set.raw_text or parameter_set.stimulation_site,
    )


def _parser_versions_for_assertion(
    *,
    assertion: EvidenceAssertion,
    chunk_parser_versions: dict[str, str],
) -> tuple[str, ...]:
    versions = {
        chunk_parser_versions[chunk_id]
        for chunk_id in assertion.source_chunk_ids
        if chunk_id in chunk_parser_versions
    }
    if not versions:
        raw_versions = assertion.metadata.get("source_parser_versions")
        if isinstance(raw_versions, (list, tuple)):
            versions.update(str(version) for version in raw_versions if version)
    return tuple(sorted(versions))


def _term_to_json(term: EvidenceTerm) -> dict[str, str | None]:
    return {
        "type": term.type.value,
        "text": term.text,
        "concept_id": term.concept_id,
        "original_text": term.original_text,
    }


def _source_quality_to_json(signals: SourceQualitySignals) -> dict[str, object]:
    return {
        "tier": signals.tier.value,
        "source_type": signals.source_type,
        "journal_quartile": signals.journal_quartile,
        "citation_count": signals.citation_count,
        "is_highly_cited": signals.is_highly_cited,
        "is_hot_paper": signals.is_hot_paper,
    }


def _parameter_set_to_json(parameter_set: ParameterSet | None) -> dict[str, object] | None:
    if parameter_set is None:
        return None
    return {
        "stimulation_site": parameter_set.stimulation_site,
        "frequency_hz": parameter_set.frequency_hz,
        "pulse_width_us": parameter_set.pulse_width_us,
        "intensity": parameter_set.intensity,
        "duration_minutes": parameter_set.duration_minutes,
        "course": parameter_set.course,
        "waveform": parameter_set.waveform,
        "dose": parameter_set.dose,
        "sham_control": parameter_set.sham_control,
        "raw_text": parameter_set.raw_text,
    }


def _assertion_to_json(assertion: EvidenceAssertion) -> dict[str, object]:
    return {
        "id": assertion.id,
        "domain_id": assertion.domain_id,
        "subject": _term_to_json(assertion.subject),
        "predicate": assertion.predicate.value,
        "object": _term_to_json(assertion.object),
        "source_chunk_ids": list(assertion.source_chunk_ids),
        "review_status": assertion.review_status.value,
        "population": assertion.population,
        "parameter_set": _parameter_set_to_json(assertion.parameter_set),
        "outcome": assertion.outcome,
        "direction": assertion.direction.value,
        "extraction_confidence": assertion.extraction_confidence,
        "source_quality_signals": _source_quality_to_json(assertion.source_quality_signals),
        "study_id": assertion.study_id,
        "valid_from": assertion.valid_from,
        "supersedes": assertion.supersedes,
        "metadata": assertion.metadata,
    }


def _normalization_candidate_to_json(candidate: StandardizationCandidate) -> dict[str, object]:
    return {
        "id": candidate.id,
        "term_role": candidate.term_role,
        "concept_type": candidate.concept_type.value,
        "original_text": candidate.original_text,
        "suggested_concept_id": candidate.suggested_concept_id,
        "suggested_preferred_name": candidate.suggested_preferred_name,
        "aliases": list(candidate.aliases),
        "status": candidate.status.value,
        "review_note": candidate.review_note,
    }


def _release_to_json(release: GraphRelease) -> dict[str, object]:
    return {
        "id": release.id,
        "domain_id": release.domain_id,
        "version": release.version,
        "included_assertion_ids": list(release.included_assertion_ids),
        "schema_version": release.schema_version,
        "index_version": release.index_version,
        "released_by": release.released_by,
        "active": release.active,
    }
