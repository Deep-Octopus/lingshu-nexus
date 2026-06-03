"""Graph storage port for published evidence releases."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

from lingshu_domain import EvidenceAssertion, GraphRelease
from lingshu_domain.validation import SchemaValidationError


@dataclass(frozen=True)
class GraphNode:
    id: str
    domain_id: str
    label: str
    properties: dict[str, str]


@dataclass(frozen=True)
class GraphRelationship:
    source_id: str
    target_id: str
    type: str
    domain_id: str
    properties: dict[str, str]


class GraphRepository(Protocol):
    def write_release(
        self,
        release: GraphRelease,
        assertions: tuple[EvidenceAssertion, ...],
    ) -> None:
        """Write approved release assertions to the graph backend."""

    def assertion_ids_for_release(self, *, domain_id: str, release_id: str) -> tuple[str, ...]:
        """Return assertion ids visible for a published release."""


class InMemoryGraphRepository:
    """Deterministic graph repository used before Neo4j adapter implementation."""

    def __init__(self) -> None:
        self._release_assertions: dict[tuple[str, str], tuple[str, ...]] = {}
        self._nodes: dict[str, GraphNode] = {}
        self._relationships: defaultdict[str, list[GraphRelationship]] = defaultdict(list)

    def write_release(
        self,
        release: GraphRelease,
        assertions: tuple[EvidenceAssertion, ...],
    ) -> None:
        for assertion in assertions:
            if assertion.domain_id != release.domain_id:
                raise SchemaValidationError("Assertion domain_id must match release domain_id")
            assertion.validate_publishable()
        provided_ids = {assertion.id for assertion in assertions}
        missing = set(release.included_assertion_ids).difference(provided_ids)
        if missing:
            raise SchemaValidationError(f"Release references missing assertions: {sorted(missing)}")

        identity = (release.domain_id, release.id)
        self._release_assertions[identity] = tuple(release.included_assertion_ids)
        for assertion in assertions:
            subject_node_id = assertion.subject.concept_id or f"term:{assertion.subject.text}"
            object_node_id = assertion.object.concept_id or f"term:{assertion.object.text}"
            self._nodes[subject_node_id] = GraphNode(
                id=subject_node_id,
                domain_id=assertion.domain_id,
                label=assertion.subject.type.value,
                properties={"text": assertion.subject.text},
            )
            self._nodes[object_node_id] = GraphNode(
                id=object_node_id,
                domain_id=assertion.domain_id,
                label=assertion.object.type.value,
                properties={"text": assertion.object.text},
            )
            self._relationships[release.id].append(
                GraphRelationship(
                    source_id=subject_node_id,
                    target_id=object_node_id,
                    type=assertion.predicate.value,
                    domain_id=assertion.domain_id,
                    properties={"assertion_id": assertion.id, "release_id": release.id},
                )
            )

    def assertion_ids_for_release(self, *, domain_id: str, release_id: str) -> tuple[str, ...]:
        return self._release_assertions.get((domain_id, release_id), ())

