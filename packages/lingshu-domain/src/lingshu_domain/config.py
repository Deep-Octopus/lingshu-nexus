"""Domain configuration for schema and terminology routing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainConfig:
    domain_id: str
    schema_version: str
    display_name: str
    allowed_concept_types: tuple[str, ...]
    allowed_predicates: tuple[str, ...]
    default_topic_tags: tuple[str, ...] = ()
    terminology_version: str = "v0.1"

    def validate_concept_type(self, concept_type: str) -> None:
        if concept_type not in self.allowed_concept_types:
            raise ValueError(f"Unsupported concept type for {self.domain_id}: {concept_type}")

    def validate_predicate(self, predicate: str) -> None:
        if predicate not in self.allowed_predicates:
            raise ValueError(f"Unsupported predicate for {self.domain_id}: {predicate}")


def build_domain_config(
    *,
    domain_id: str,
    schema_version: str,
    display_name: str,
    allowed_concept_types: tuple[str, ...],
    allowed_predicates: tuple[str, ...],
    default_topic_tags: tuple[str, ...] = (),
    terminology_version: str = "v0.1",
) -> DomainConfig:
    """Create a domain config without changing generic schema code."""

    if not domain_id:
        raise ValueError("domain_id is required")
    return DomainConfig(
        domain_id=domain_id,
        schema_version=schema_version,
        display_name=display_name,
        allowed_concept_types=allowed_concept_types,
        allowed_predicates=allowed_predicates,
        default_topic_tags=default_topic_tags,
        terminology_version=terminology_version,
    )


ACUPUNCTURE_DOMAIN = build_domain_config(
    domain_id="acupuncture",
    schema_version="acupuncture-tvns-v0.1.0",
    display_name="针灸证据域",
    allowed_concept_types=(
        "disease_or_symptom",
        "acupoint",
        "acupoint_combination",
        "intervention",
        "parameter",
        "outcome",
        "safety",
        "literature",
        "stimulation_site",
        "mechanism",
        "population",
    ),
    allowed_predicates=(
        "affects_outcome",
        "treats",
        "has_parameter",
        "has_outcome",
        "has_safety_event",
        "contraindicated_for",
        "uses_stimulation_site",
        "has_mechanism",
        "compared_with",
        "mentioned_in",
        "related_to",
    ),
    default_topic_tags=("tVNS", "taVNS"),
)

ADDICTION_DOMAIN = build_domain_config(
    domain_id="addiction",
    schema_version="addiction-non-pharma-v0.1.0",
    display_name="成瘾非药物干预证据域",
    allowed_concept_types=(
        "addictive_disorder",
        "substance",
        "behavioral_addiction",
        "intervention",
        "psychological_intervention",
        "physical_intervention",
        "digital_intervention",
        "intervention_parameter",
        "outcome_measure",
        "craving_measure",
        "withdrawal_symptom",
        "relapse_measure",
        "adverse_event",
        "control_condition",
        "study_design",
        "population",
        "followup_period",
        "mechanism",
        "literature",
        "barrier",
        "risk_factor",
    ),
    allowed_predicates=(
        "treats",
        "reduces_symptom",
        "improves_outcome",
        "reduces_craving",
        "reduces_relapse",
        "reduces_withdrawal",
        "has_adverse_event",
        "compared_with",
        "has_parameter",
        "has_followup",
        "targets_population",
        "uses_control",
        "has_mechanism",
        "has_study_design",
        "mentioned_in",
        "related_to",
        "associated_with",
    ),
    default_topic_tags=("addiction", "non-pharmacological intervention", "CBT", "mindfulness", "neuromodulation"),
)

DOMAIN_REGISTRY: dict[str, DomainConfig] = {
    ACUPUNCTURE_DOMAIN.domain_id: ACUPUNCTURE_DOMAIN,
    ADDICTION_DOMAIN.domain_id: ADDICTION_DOMAIN,
}


def get_domain_config(domain_id: str) -> DomainConfig:
    """Get domain configuration by ID, default to acupuncture if not found."""
    return DOMAIN_REGISTRY.get(domain_id, ACUPUNCTURE_DOMAIN)
