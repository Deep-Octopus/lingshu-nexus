"""Candidate evidence extraction use case."""

from __future__ import annotations

import json
import logging
import time
from hashlib import sha256
from typing import Any
from uuid import uuid4

from lingshu_domain import (
    ConceptType,
    Direction,
    EvidenceAssertion,
    EvidenceTerm,
    ParameterSet,
    PredicateType,
    ReviewStatus,
    SourceChunk,
    SourceQualitySignals,
    SourceQualityTier,
)
from lingshu_domain.validation import SchemaValidationError, require_domain_id
from lingshu_nexus.documents.models import DocumentRecord, DocumentStatus
from lingshu_nexus.extraction.models import (
    CandidateExtractionRun,
    CandidateRelation,
    ExtractionPrompt,
    ExtractionSchemaVersion,
    ProviderUsage,
)
from lingshu_nexus.extraction.providers import LlmCompletionRequest, LlmProvider, ProviderError
from lingshu_nexus.extraction.prompts import load_literature_extraction_prompt
from lingshu_nexus.extraction.repository import CandidateRepository
from lingshu_nexus.observability import ObservabilityRecorder, ObservationStatus
from lingshu_nexus.persistence.models import DataLayer, JobStatus
from lingshu_nexus.persistence.object_store import ObjectRef, ObjectStore


class CandidateExtractionError(ValueError):
    """Raised when structured candidate extraction fails validation."""

_LOGGER = logging.getLogger(__name__)


class CandidateExtractionService:
    def __init__(
        self,
        *,
        repository: CandidateRepository,
        object_store: ObjectStore,
        provider: LlmProvider,
        prompt: ExtractionPrompt | None = None,
        schema_version: str = ExtractionSchemaVersion.CANDIDATE_V0_1.value,
        observability: ObservabilityRecorder | None = None,
    ) -> None:
        self._repository = repository
        self._object_store = object_store
        self._provider = provider
        self._default_prompt = prompt
        self._prompt_cache: dict[str, ExtractionPrompt] = {}
        self._schema_version = schema_version
        self._observability = observability

    def _get_prompt_for_domain(self, domain_id: str) -> ExtractionPrompt:
        """Get or load the appropriate extraction prompt for the given domain."""
        if domain_id in self._prompt_cache:
            cached = self._prompt_cache[domain_id]
            _LOGGER.info(
                "Using cached extraction prompt for domain %s: %s (checksum=%s)",
                domain_id,
                cached.id,
                cached.checksum,
            )
            return cached

        # Try to load domain-specific prompt, fall back to default if not found
        try:
            prompt = load_literature_extraction_prompt(domain_id)
            _LOGGER.info(
                "Loaded extraction prompt for domain %s: %s (checksum=%s)",
                domain_id,
                prompt.id,
                prompt.checksum,
            )
        except FileNotFoundError:
            # Fall back to default prompt (acupuncture) if domain-specific prompt not found
            prompt = self._default_prompt or load_literature_extraction_prompt("acupuncture")
            _LOGGER.warning(
                "Extraction prompt not found for domain %s, falling back to default (%s)",
                domain_id,
                prompt.id,
            )

        self._prompt_cache[domain_id] = prompt
        return prompt

    def extract_document(self, document: DocumentRecord) -> CandidateExtractionRun:
        require_domain_id(document.domain_id)
        if document.status is not DocumentStatus.PARSED:
            return self._failed_run(
                document=document,
                provider=getattr(self._provider, "name", "unknown"),
                model="unknown",
                source_chunk_ids=tuple(chunk.id for chunk in document.chunks) or ("unknown",),
                failure_reason=(
                    f"Document must be PARSED before extraction, got {document.status.value}"
                ),
            )
        if not document.chunks:
            return self._failed_run(
                document=document,
                provider=getattr(self._provider, "name", "unknown"),
                model="unknown",
                source_chunk_ids=("unknown",),
                failure_reason="Document has no chunks to extract",
            )

        source_chunk_ids = tuple(chunk.id for chunk in document.chunks)
        started = time.perf_counter()
        prompt = self._get_prompt_for_domain(document.domain_id)
        try:
            provider_response = self._provider.complete(
                LlmCompletionRequest(
                    system_prompt=prompt.text,
                    user_prompt=_build_user_prompt(document),
                    prompt_version=prompt.version,
                    schema_version=self._schema_version,
                    metadata={
                        "domain_id": document.domain_id,
                        "document_id": document.id,
                        "chunk_count": len(document.chunks),
                    },
                )
            )
            parsed_payload = _load_json_object(provider_response.text)
            parsed = _parse_candidate_payload(
                payload=parsed_payload,
                domain_id=document.domain_id,
                document_id=document.id,
                source_chunks=document.chunks,
            )
            latency_ms = provider_response.latency_ms
            if latency_ms is None:
                latency_ms = int((time.perf_counter() - started) * 1000)
            run_id = f"extract_{uuid4().hex}"
            run = CandidateExtractionRun(
                id=run_id,
                domain_id=document.domain_id,
                document_id=document.id,
                status=JobStatus.SUCCEEDED,
                provider=provider_response.provider,
                model=provider_response.model,
                prompt_version=prompt.version,
                schema_version=self._schema_version,
                source_chunk_ids=source_chunk_ids,
                evidence_assertions=parsed.evidence_assertions,
                relations=parsed.relations,
                entities=parsed.entities,
                study_metadata=parsed.study_metadata,
                token_usage=provider_response.token_usage,
                latency_ms=latency_ms,
                raw_response_hash=sha256(provider_response.text.encode("utf-8")).hexdigest(),
            )
            output_ref = self._store_candidate_artifact(run, provider_response.text)
            run = _replace_output_ref(run, output_ref)
            self._repository.add_run(run)
            self._record_model_observation(
                run=run,
                status=ObservationStatus.SUCCEEDED,
                chunk_count=len(document.chunks),
            )
            return run
        except (ProviderError, CandidateExtractionError, SchemaValidationError) as exc:
            return self._failed_run(
                document=document,
                provider=getattr(self._provider, "name", "unknown"),
                model="unknown",
                source_chunk_ids=source_chunk_ids,
                failure_reason=str(exc),
            )

    def _failed_run(
        self,
        *,
        document: DocumentRecord,
        provider: str,
        model: str,
        source_chunk_ids: tuple[str, ...],
        failure_reason: str,
    ) -> CandidateExtractionRun:
        prompt = self._get_prompt_for_domain(document.domain_id)
        run = CandidateExtractionRun(
            id=f"extract_{uuid4().hex}",
            domain_id=document.domain_id,
            document_id=document.id,
            status=JobStatus.FAILED,
            provider=provider,
            model=model,
            prompt_version=prompt.version,
            schema_version=self._schema_version,
            source_chunk_ids=source_chunk_ids,
            failure_reason=failure_reason,
        )
        self._repository.add_run(run)
        self._record_model_observation(
            run=run,
            status=ObservationStatus.FAILED,
            chunk_count=len(document.chunks),
            error=failure_reason,
        )
        return run

    def _store_candidate_artifact(
        self,
        run: CandidateExtractionRun,
        raw_response_text: str,
    ) -> ObjectRef:
        artifact = {
            "run_id": run.id,
            "domain_id": run.domain_id,
            "document_id": run.document_id,
            "provider": run.provider,
            "model": run.model,
            "prompt_version": run.prompt_version,
            "schema_version": run.schema_version,
            "token_usage": _usage_to_json(run.token_usage),
            "raw_response_hash": run.raw_response_hash,
            "raw_response": _load_json_object(raw_response_text),
            "entities": [_term_to_json(entity) for entity in run.entities],
            "relations": [_relation_to_json(relation) for relation in run.relations],
            "evidence_assertions": [
                _assertion_to_json(assertion) for assertion in run.evidence_assertions
            ],
            "study_metadata": run.study_metadata,
        }
        return self._object_store.put(
            domain_id=run.domain_id,
            object_key=f"documents/{run.document_id}/candidate/{run.id}.json",
            content=json.dumps(artifact, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            layer=DataLayer.CANDIDATE,
            media_type="application/json",
            version=1,
        )

    def _record_model_observation(
        self,
        *,
        run: CandidateExtractionRun,
        status: ObservationStatus,
        chunk_count: int,
        error: str | None = None,
    ) -> None:
        if self._observability is None:
            return
        self._observability.record(
            event_type="model.extraction",
            status=status,
            domain_id=run.domain_id,
            target_type="document",
            target_id=run.document_id,
            trace_id=run.id,
            config_versions=(run.prompt_version, run.schema_version),
            metrics={
                "chunk_count": chunk_count,
                "latency_ms": run.latency_ms,
                "prompt_tokens": run.token_usage.prompt_tokens,
                "completion_tokens": run.token_usage.completion_tokens,
                "total_tokens": run.token_usage.total_tokens,
                "estimated_cost": run.token_usage.estimated_cost,
            },
            metadata={
                "provider": run.provider,
                "model": run.model,
                "assertion_count": len(run.evidence_assertions),
                "raw_response_hash": run.raw_response_hash,
            },
            error=error,
        )


class _ParsedCandidatePayload:
    def __init__(
        self,
        *,
        entities: tuple[EvidenceTerm, ...],
        relations: tuple[CandidateRelation, ...],
        evidence_assertions: tuple[EvidenceAssertion, ...],
        study_metadata: dict[str, Any],
    ) -> None:
        self.entities = entities
        self.relations = relations
        self.evidence_assertions = evidence_assertions
        self.study_metadata = study_metadata


def _build_user_prompt(document: DocumentRecord) -> str:
    chunks = [
        {
            "id": chunk.id,
            "locator": chunk.locator.as_reference(),
            "text": chunk.text,
        }
        for chunk in document.chunks
    ]
    payload = {
        "domain_id": document.domain_id,
        "document_id": document.id,
        "title": document.title,
        "chunks": chunks,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _load_json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CandidateExtractionError(f"Provider output is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CandidateExtractionError("Provider output must be a JSON object")
    return payload


def _parse_candidate_payload(
    *,
    payload: dict[str, Any],
    domain_id: str,
    document_id: str,
    source_chunks: tuple[SourceChunk, ...],
) -> _ParsedCandidatePayload:
    allowed_chunk_ids = {chunk.id for chunk in source_chunks}
    chunk_parser_versions = {chunk.id: chunk.parser_version for chunk in source_chunks}
    entities: list[EvidenceTerm] = []
    for item in _list(payload.get("entities")):
        try:
            entities.append(_parse_term(item, "entities[]"))
        except CandidateExtractionError as exc:
            _LOGGER.warning("Skipping unparseable entity in extraction result: %s", exc)
    relations: list[CandidateRelation] = []
    relation_errors: list[str] = []
    for index, item in enumerate(_list(payload.get("relations"))):
        try:
            relations.append(
                _parse_relation(
                    item,
                    index=index,
                    domain_id=domain_id,
                    allowed_chunk_ids=allowed_chunk_ids,
                )
            )
        except CandidateExtractionError as exc:
            _LOGGER.warning("Skipping unparseable relation[%d] in extraction result: %s", index, exc)
            relation_errors.append(str(exc))
    assertions: list[EvidenceAssertion] = []
    assertion_errors: list[str] = []
    for index, item in enumerate(_list(payload.get("evidence_assertions"))):
        try:
            assertions.append(
                _parse_assertion(
                    item,
                    index=index,
                    domain_id=domain_id,
                    document_id=document_id,
                    allowed_chunk_ids=allowed_chunk_ids,
                    chunk_parser_versions=chunk_parser_versions,
                )
            )
        except CandidateExtractionError as exc:
            _LOGGER.warning(
                "Skipping unparseable evidence_assertion[%d] in extraction result: %s", index, exc
            )
            assertion_errors.append(str(exc))
    raw_assertions = _list(payload.get("evidence_assertions"))
    raw_relations = _list(payload.get("relations"))
    if raw_assertions and not assertions:
        raise CandidateExtractionError(
            f"All {len(raw_assertions)} evidence_assertion(s) failed validation: "
            + "; ".join(assertion_errors)
        )
    if raw_relations and not relations:
        _LOGGER.warning(
            "All %d relation(s) failed validation (non-fatal): %s",
            len(raw_relations),
            "; ".join(relation_errors),
        )
    study = payload.get("study", {})
    if study is None:
        study = {}
    if not isinstance(study, dict):
        raise CandidateExtractionError("study must be an object when present")
    return _ParsedCandidatePayload(
        entities=tuple(entities),
        relations=tuple(relations),
        evidence_assertions=tuple(assertions),
        study_metadata=study,
    )


def _parse_relation(
    item: object,
    *,
    index: int,
    domain_id: str,
    allowed_chunk_ids: set[str],
) -> CandidateRelation:
    value = _object(item, "relations[]")
    source_chunk_ids = _source_chunk_ids(value, allowed_chunk_ids)
    predicate_raw = str(value.get("predicate"))
    try:
        predicate = PredicateType(predicate_raw)
    except ValueError as exc:
        raise CandidateExtractionError(
            f"Unknown predicate type: {predicate_raw!r}"
        ) from exc
    return CandidateRelation(
        id=str(value.get("id") or f"relation_{index:04d}"),
        domain_id=domain_id,
        subject=_parse_term(value.get("subject"), "relation.subject"),
        predicate=predicate,
        object=_parse_term(value.get("object"), "relation.object"),
        source_chunk_ids=source_chunk_ids,
        confidence=float(value.get("confidence", 0)),
    )


def _parse_assertion(
    item: object,
    *,
    index: int,
    domain_id: str,
    document_id: str,
    allowed_chunk_ids: set[str],
    chunk_parser_versions: dict[str, str],
) -> EvidenceAssertion:
    value = _object(item, "evidence_assertions[]")
    source_chunk_ids = _source_chunk_ids(value, allowed_chunk_ids)
    predicate_raw = str(value.get("predicate"))
    try:
        predicate = PredicateType(predicate_raw)
    except ValueError as exc:
        raise CandidateExtractionError(
            f"Unknown predicate type: {predicate_raw!r}"
        ) from exc
    metadata = _object_or_empty(value.get("metadata"))
    metadata["source_parser_versions"] = sorted(
        {
            chunk_parser_versions[chunk_id]
            for chunk_id in source_chunk_ids
            if chunk_id in chunk_parser_versions
        }
    )
    assertion = EvidenceAssertion(
        id=str(value.get("id") or f"candidate_{document_id}_{index:04d}"),
        domain_id=domain_id,
        subject=_parse_term(value.get("subject"), "assertion.subject"),
        predicate=predicate,
        object=_parse_term(value.get("object"), "assertion.object"),
        source_chunk_ids=source_chunk_ids,
        review_status=ReviewStatus.PENDING,
        population=_optional_str(value.get("population")),
        parameter_set=_parse_parameter_set(value.get("parameter_set")),
        outcome=_optional_str(value.get("outcome")),
        direction=Direction(str(value.get("direction", Direction.UNCLEAR.value))),
        extraction_confidence=float(value.get("extraction_confidence", 0)),
        source_quality_signals=_parse_source_quality_signals(value.get("source_quality_signals")),
        metadata=metadata,
    )
    if not assertion.source_chunk_ids:
        raise CandidateExtractionError("EvidenceAssertion must include source_chunk_ids")
    return assertion


# Mapping of common LLM-generated concept type strings to valid ConceptType values.
# DeepSeek and other models sometimes produce types (e.g. "condition") that are not
# in the official enum. This mapping prevents ValueErrors at parse time.
_CONCEPT_TYPE_FALLBACK: dict[str, str] = {
    # Common fallbacks
    "condition": "disease_or_symptom",
    "disease": "disease_or_symptom",
    "symptom": "disease_or_symptom",
    "disorder": "addictive_disorder",
    "syndrome": "disease_or_symptom",
    "treatment": "intervention",
    "therapy": "psychological_intervention",
    "drug": "intervention",
    "procedure": "physical_intervention",
    "device": "physical_intervention",
    "point": "acupoint",
    "site": "stimulation_site",
    "side_effect": "adverse_event",
    "adverse_event": "adverse_event",
    "adverse_effect": "adverse_event",
    "safety": "adverse_event",
    "study_design": "study_design",
    "article": "literature",
    "paper": "literature",
    "publication": "literature",

    # Addiction specific fallbacks
    "addiction": "addictive_disorder",
    "dependence": "addictive_disorder",
    "substance_use": "addictive_disorder",
    "substance_abuse": "addictive_disorder",
    "alcohol_addiction": "addictive_disorder",
    "opioid_addiction": "addictive_disorder",
    "nicotine_addiction": "addictive_disorder",
    "smoking": "addictive_disorder",
    "tobacco": "substance",
    "alcohol": "substance",
    "opioid": "substance",
    "cocaine": "substance",
    "methamphetamine": "substance",
    "cannabis": "substance",
    "marijuana": "substance",
    "behavioral_addiction": "behavioral_addiction",
    "gambling": "behavioral_addiction",
    "internet_addiction": "behavioral_addiction",
    "gaming_disorder": "behavioral_addiction",
    "psychotherapy": "psychological_intervention",
    "cbt": "psychological_intervention",
    "cognitive_behavioral": "psychological_intervention",
    "motivational_interviewing": "psychological_intervention",
    "mi": "psychological_intervention",
    "mindfulness": "psychological_intervention",
    "contingency_management": "psychological_intervention",
    "cm": "psychological_intervention",
    "family_therapy": "psychological_intervention",
    "acupuncture": "physical_intervention",
    "electroacupuncture": "physical_intervention",
    "rtms": "physical_intervention",
    "tdcs": "physical_intervention",
    "vagus_nerve_stimulation": "physical_intervention",
    "tvns": "physical_intervention",
    "exercise": "physical_intervention",
    "digital_intervention": "digital_intervention",
    "internet_intervention": "digital_intervention",
    "app_intervention": "digital_intervention",
    "mobile_intervention": "digital_intervention",
    "icbt": "digital_intervention",
    "online_therapy": "digital_intervention",
    "parameter": "intervention_parameter",
    "outcome": "outcome_measure",
    "abstinence": "outcome_measure",
    "retention": "outcome_measure",
    "craving": "craving_measure",
    "withdrawal": "withdrawal_symptom",
    "relapse": "relapse_measure",
    "control": "control_condition",
    "followup": "followup_period",
    "follow_up": "followup_period",
    "population": "population",
    "mechanism": "mechanism",
}


def _resolve_concept_type(raw: str) -> ConceptType:
    """Convert a raw type string to a ConceptType, with fallback for LLM variants."""
    try:
        return ConceptType(raw)
    except ValueError:
        mapped = _CONCEPT_TYPE_FALLBACK.get(raw.lower().strip())
        if mapped is not None:
            return ConceptType(mapped)
        raise CandidateExtractionError(
            f"Unknown concept type {raw!r} is not a valid ConceptType; "
            "add a fallback mapping in _CONCEPT_TYPE_FALLBACK if this is a legitimate variant"
        ) from None


def _parse_term(item: object, field_name: str) -> EvidenceTerm:
    value = _object(item, field_name)
    return EvidenceTerm(
        type=_resolve_concept_type(str(value.get("type"))),
        text=str(value.get("text") or ""),
        concept_id=_optional_str(value.get("concept_id")),
        original_text=_optional_str(value.get("original_text")),
    )


def _source_chunk_ids(value: dict[str, Any], allowed_chunk_ids: set[str]) -> tuple[str, ...]:
    ids = tuple(str(item) for item in _list(value.get("source_chunk_ids")))
    if not ids:
        raise CandidateExtractionError("source_chunk_ids must not be empty")
    unknown = sorted(set(ids).difference(allowed_chunk_ids))
    if unknown:
        raise CandidateExtractionError(f"source_chunk_ids reference unknown chunks: {unknown}")
    return ids


def _parse_parameter_set(item: object) -> ParameterSet | None:
    if item is None:
        return None
    value = _object(item, "parameter_set")
    return ParameterSet(
        # Acupuncture/tVNS parameters
        stimulation_site=_optional_str(value.get("stimulation_site")),
        frequency_hz=_optional_float(value.get("frequency_hz")),
        pulse_width_us=_optional_float(value.get("pulse_width_us")),
        intensity=_optional_str(value.get("intensity")),
        duration_minutes=_optional_float(value.get("duration_minutes")),
        course=_optional_str(value.get("course")),
        waveform=_optional_str(value.get("waveform")),
        dose=_optional_str(value.get("dose")),
        sham_control=_optional_str(value.get("sham_control")),

        # Addiction intervention parameters
        intervention_type=_optional_str(value.get("intervention_type")),
        delivery_format=_optional_str(value.get("delivery_format")),
        session_frequency=_optional_str(value.get("session_frequency")),
        total_duration_weeks=_optional_float(value.get("total_duration_weeks")),
        total_sessions=_optional_int(value.get("total_sessions")),
        therapist_qualification=_optional_str(value.get("therapist_qualification")),
        delivery_setting=_optional_str(value.get("delivery_setting")),
        dose_response=_optional_str(value.get("dose_response")),
        adherence_rate=_optional_float(value.get("adherence_rate")),
        control_condition=_optional_str(value.get("control_condition")),
        followup_period_months=_optional_float(value.get("followup_period_months")),
        abstinence_definition=_optional_str(value.get("abstinence_definition")),

        raw_text=_optional_str(value.get("raw_text")),
    )


def _parse_source_quality_signals(item: object) -> SourceQualitySignals:
    if item is None:
        return SourceQualitySignals()
    value = _object(item, "source_quality_signals")
    tier = SourceQualityTier(str(value.get("tier", SourceQualityTier.UNKNOWN.value)))
    return SourceQualitySignals(
        tier=tier,
        source_type=_optional_str(value.get("source_type")),
        journal_quartile=_optional_str(value.get("journal_quartile")),
        citation_count=_optional_int(value.get("citation_count")),
        is_highly_cited=bool(value.get("is_highly_cited", False)),
        is_hot_paper=bool(value.get("is_hot_paper", False)),
    )


def _list(item: object) -> list[object]:
    if item is None:
        return []
    if not isinstance(item, list):
        raise CandidateExtractionError("Expected a JSON array")
    return item


def _object(item: object, field_name: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise CandidateExtractionError(f"{field_name} must be an object")
    return item


def _object_or_empty(item: object) -> dict[str, Any]:
    if item is None:
        return {}
    return _object(item, "metadata")


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float | str | bytes | bytearray):
        return float(value)
    raise CandidateExtractionError(f"Expected numeric value, got {value!r}")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str | bytes | bytearray):
        return int(value)
    raise CandidateExtractionError(f"Expected integer value, got {value!r}")


def _replace_output_ref(
    run: CandidateExtractionRun,
    output_ref: ObjectRef,
) -> CandidateExtractionRun:
    return CandidateExtractionRun(
        id=run.id,
        domain_id=run.domain_id,
        document_id=run.document_id,
        status=run.status,
        provider=run.provider,
        model=run.model,
        prompt_version=run.prompt_version,
        schema_version=run.schema_version,
        source_chunk_ids=run.source_chunk_ids,
        evidence_assertions=run.evidence_assertions,
        relations=run.relations,
        entities=run.entities,
        study_metadata=run.study_metadata,
        token_usage=run.token_usage,
        latency_ms=run.latency_ms,
        raw_response_hash=run.raw_response_hash,
        output_ref=output_ref,
        failure_reason=run.failure_reason,
        created_at=run.created_at,
    )


def _usage_to_json(usage: ProviderUsage) -> dict[str, int | float | None]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "estimated_cost": usage.estimated_cost,
    }


def _term_to_json(term: EvidenceTerm) -> dict[str, str | None]:
    return {
        "type": term.type.value,
        "text": term.text,
        "concept_id": term.concept_id,
        "original_text": term.original_text,
    }


def _relation_to_json(relation: CandidateRelation) -> dict[str, object]:
    return {
        "id": relation.id,
        "subject": _term_to_json(relation.subject),
        "predicate": relation.predicate.value,
        "object": _term_to_json(relation.object),
        "source_chunk_ids": list(relation.source_chunk_ids),
        "confidence": relation.confidence,
    }


def _assertion_to_json(assertion: EvidenceAssertion) -> dict[str, object]:
    return {
        "id": assertion.id,
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
        "source_quality_signals": {
            "tier": assertion.source_quality_signals.tier.value,
            "source_type": assertion.source_quality_signals.source_type,
            "journal_quartile": assertion.source_quality_signals.journal_quartile,
            "citation_count": assertion.source_quality_signals.citation_count,
            "is_highly_cited": assertion.source_quality_signals.is_highly_cited,
            "is_hot_paper": assertion.source_quality_signals.is_hot_paper,
        },
        "metadata": assertion.metadata,
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
