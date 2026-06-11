"""Graph storage ports for published evidence releases."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol

from lingshu_domain import (
    EvidenceAssertion,
    EvidenceTerm,
    GraphRelease,
    SourceChunk,
    SourceDocument,
)
from lingshu_domain.validation import SchemaValidationError, require_domain_id, require_text


@dataclass(frozen=True)
class GraphNode:
    id: str
    domain_id: str
    release_id: str
    label: str
    properties: dict[str, str]


@dataclass(frozen=True)
class GraphRelationship:
    source_id: str
    target_id: str
    type: str
    domain_id: str
    release_id: str
    properties: dict[str, str]


@dataclass(frozen=True)
class GraphSourceReference:
    domain_id: str
    release_id: str
    document_id: str
    chunk_id: str
    locator_reference: str | None = None
    document_title: str | None = None
    source_uri: str | None = None
    chunk_text: str | None = None
    parser_version: str | None = None


class GraphRepository(Protocol):
    def write_release(
        self,
        release: GraphRelease,
        assertions: tuple[EvidenceAssertion, ...],
        *,
        source_documents: tuple[SourceDocument, ...] = (),
        source_chunks: tuple[SourceChunk, ...] = (),
    ) -> None:
        """Write approved release assertions to the graph backend."""

    def set_active_release(self, *, domain_id: str, release_id: str) -> None:
        """Set the release visible to user retrieval in one domain."""

    def active_release_id(self, *, domain_id: str) -> str | None:
        """Return the graph release currently visible for user retrieval."""

    def assertion_ids_for_release(self, *, domain_id: str, release_id: str) -> tuple[str, ...]:
        """Return assertion ids visible for a published release."""

    def list_assertions_for_release(
        self,
        *,
        domain_id: str,
        release_id: str,
    ) -> tuple[EvidenceAssertion, ...]:
        """Return publishable assertions for one release."""

    def get_release(self, *, domain_id: str, release_id: str) -> GraphRelease:
        """Return release metadata from the graph backend."""

    def find_concepts(
        self,
        *,
        domain_id: str,
        release_id: str | None = None,
        query: str | None = None,
    ) -> tuple[GraphNode, ...]:
        """Find concept or literal-term nodes in one release."""

    def relationships_for_concept(
        self,
        *,
        domain_id: str,
        release_id: str | None = None,
        concept_id: str | None = None,
        text: str | None = None,
    ) -> tuple[GraphRelationship, ...]:
        """Return release-local relationships adjacent to a concept or term."""

    def source_references_for_assertion(
        self,
        *,
        domain_id: str,
        release_id: str,
        assertion_id: str,
    ) -> tuple[GraphSourceReference, ...]:
        """Return source documents and chunks cited by one published assertion."""

    def source_documents_for_release(
        self,
        *,
        domain_id: str,
        release_id: str,
    ) -> tuple[SourceDocument, ...]:
        """Return source documents cited by a published release."""


class InMemoryGraphRepository:
    """Deterministic graph repository for tests and local baseline retrieval."""

    def __init__(self) -> None:
        self._release_assertions: dict[tuple[str, str], tuple[str, ...]] = {}
        self._releases: dict[tuple[str, str], GraphRelease] = {}
        self._assertions: dict[tuple[str, str, str], EvidenceAssertion] = {}
        self._source_chunks: dict[tuple[str, str, str], SourceChunk] = {}
        self._source_documents: dict[tuple[str, str, str], SourceDocument] = {}
        self._nodes: dict[str, GraphNode] = {}
        self._release_node_ids: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
        self._relationships: defaultdict[tuple[str, str], list[GraphRelationship]] = defaultdict(
            list
        )
        self._active_releases: dict[str, str] = {}

    def write_release(
        self,
        release: GraphRelease,
        assertions: tuple[EvidenceAssertion, ...],
        *,
        source_documents: tuple[SourceDocument, ...] = (),
        source_chunks: tuple[SourceChunk, ...] = (),
    ) -> None:
        for source_document in source_documents:
            if source_document.domain_id != release.domain_id:
                raise SchemaValidationError("SourceDocument domain_id must match release domain_id")
        for source_chunk in source_chunks:
            if source_chunk.domain_id != release.domain_id:
                raise SchemaValidationError("SourceChunk domain_id must match release domain_id")

        assertions_by_id = {assertion.id: assertion for assertion in assertions}
        missing = set(release.included_assertion_ids).difference(assertions_by_id)
        if missing:
            raise SchemaValidationError(f"Release references missing assertions: {sorted(missing)}")

        ordered_assertions = tuple(
            assertions_by_id[assertion_id] for assertion_id in release.included_assertion_ids
        )
        for assertion in ordered_assertions:
            if assertion.domain_id != release.domain_id:
                raise SchemaValidationError("Assertion domain_id must match release domain_id")
            assertion.validate_publishable()

        identity = (release.domain_id, release.id)
        self._release_assertions[identity] = tuple(release.included_assertion_ids)
        self._releases[identity] = release
        self._relationships[identity] = []
        self._release_node_ids[identity] = set()
        for source_document in source_documents:
            self._source_documents[(release.domain_id, release.id, source_document.id)] = (
                source_document
            )
        for source_chunk in source_chunks:
            self._source_chunks[(release.domain_id, release.id, source_chunk.id)] = source_chunk

        for assertion in ordered_assertions:
            self._assertions[(release.domain_id, release.id, assertion.id)] = assertion
            subject_node_id = _node_id_for_term(release.domain_id, assertion.subject)
            object_node_id = _node_id_for_term(release.domain_id, assertion.object)
            self._release_node_ids[identity].update({subject_node_id, object_node_id})
            self._nodes[subject_node_id] = GraphNode(
                id=subject_node_id,
                domain_id=assertion.domain_id,
                release_id=release.id,
                label=assertion.subject.type.value,
                properties=_term_properties(assertion.subject),
            )
            self._nodes[object_node_id] = GraphNode(
                id=object_node_id,
                domain_id=assertion.domain_id,
                release_id=release.id,
                label=assertion.object.type.value,
                properties=_term_properties(assertion.object),
            )
            self._relationships[identity].append(
                GraphRelationship(
                    source_id=subject_node_id,
                    target_id=object_node_id,
                    type=assertion.predicate.value,
                    domain_id=assertion.domain_id,
                    release_id=release.id,
                    properties={
                        "assertion_id": assertion.id,
                        "release_id": release.id,
                        "review_status": assertion.review_status.value,
                    },
                )
            )
        if release.active:
            self.set_active_release(domain_id=release.domain_id, release_id=release.id)

    def set_active_release(self, *, domain_id: str, release_id: str) -> None:
        require_domain_id(domain_id)
        require_text(release_id, "release_id")
        if (domain_id, release_id) not in self._releases:
            raise KeyError(release_id)
        self._active_releases[domain_id] = release_id

    def active_release_id(self, *, domain_id: str) -> str | None:
        require_domain_id(domain_id)
        return self._active_releases.get(domain_id)

    def assertion_ids_for_release(self, *, domain_id: str, release_id: str) -> tuple[str, ...]:
        require_domain_id(domain_id)
        require_text(release_id, "release_id")
        return self._release_assertions.get((domain_id, release_id), ())

    def list_assertions_for_release(
        self,
        *,
        domain_id: str,
        release_id: str,
    ) -> tuple[EvidenceAssertion, ...]:
        require_domain_id(domain_id)
        require_text(release_id, "release_id")
        assertion_ids = self.assertion_ids_for_release(domain_id=domain_id, release_id=release_id)
        return tuple(
            self._assertions[(domain_id, release_id, assertion_id)]
            for assertion_id in assertion_ids
            if (domain_id, release_id, assertion_id) in self._assertions
        )

    def get_release(self, *, domain_id: str, release_id: str) -> GraphRelease:
        require_domain_id(domain_id)
        require_text(release_id, "release_id")
        try:
            return self._releases[(domain_id, release_id)]
        except KeyError as exc:
            raise KeyError(release_id) from exc

    def find_concepts(
        self,
        *,
        domain_id: str,
        release_id: str | None = None,
        query: str | None = None,
    ) -> tuple[GraphNode, ...]:
        release_id = self._resolve_release_id(domain_id=domain_id, release_id=release_id)
        node_ids = self._release_node_ids.get((domain_id, release_id), set())
        nodes = [self._nodes[node_id] for node_id in node_ids if node_id in self._nodes]
        if query is not None and query.strip():
            needle = query.casefold()
            nodes = [
                node
                for node in nodes
                if needle in " ".join(node.properties.values()).casefold()
                or needle in node.id.casefold()
            ]
        return tuple(sorted(nodes, key=lambda node: (node.label, node.properties.get("text", ""))))

    def relationships_for_concept(
        self,
        *,
        domain_id: str,
        release_id: str | None = None,
        concept_id: str | None = None,
        text: str | None = None,
    ) -> tuple[GraphRelationship, ...]:
        release_id = self._resolve_release_id(domain_id=domain_id, release_id=release_id)
        if concept_id is None and text is None:
            raise SchemaValidationError("concept_id or text is required")
        node_ids = {
            node.id
            for node in self.find_concepts(domain_id=domain_id, release_id=release_id)
            if (concept_id is not None and node.properties.get("concept_id") == concept_id)
            or (text is not None and node.properties.get("text", "").casefold() == text.casefold())
        }
        if not node_ids:
            return ()
        return tuple(
            relationship
            for relationship in self._relationships.get((domain_id, release_id), ())
            if relationship.source_id in node_ids or relationship.target_id in node_ids
        )

    def source_references_for_assertion(
        self,
        *,
        domain_id: str,
        release_id: str,
        assertion_id: str,
    ) -> tuple[GraphSourceReference, ...]:
        require_domain_id(domain_id)
        require_text(release_id, "release_id")
        require_text(assertion_id, "assertion_id")
        assertion = self._assertions.get((domain_id, release_id, assertion_id))
        if assertion is None:
            return ()
        references: list[GraphSourceReference] = []
        for chunk_id in assertion.source_chunk_ids:
            chunk = self._source_chunks.get((domain_id, release_id, chunk_id))
            if chunk is None:
                references.append(
                    GraphSourceReference(
                        domain_id=domain_id,
                        release_id=release_id,
                        document_id="",
                        chunk_id=chunk_id,
                    )
                )
                continue
            document = self._source_documents.get((domain_id, release_id, chunk.document_id))
            references.append(
                GraphSourceReference(
                    domain_id=domain_id,
                    release_id=release_id,
                    document_id=chunk.document_id,
                    chunk_id=chunk.id,
                    locator_reference=chunk.locator.as_reference(),
                    document_title=document.title if document else None,
                    source_uri=document.source_uri if document else None,
                    chunk_text=chunk.text,
                    parser_version=chunk.parser_version,
                )
            )
        return tuple(references)

    def source_documents_for_release(
        self,
        *,
        domain_id: str,
        release_id: str,
    ) -> tuple[SourceDocument, ...]:
        require_domain_id(domain_id)
        require_text(release_id, "release_id")
        documents = [
            document
            for (document_domain_id, document_release_id, _), document in (
                self._source_documents.items()
            )
            if document_domain_id == domain_id and document_release_id == release_id
        ]
        return tuple(sorted(documents, key=lambda document: document.id))

    def _resolve_release_id(self, *, domain_id: str, release_id: str | None) -> str:
        require_domain_id(domain_id)
        if release_id is not None:
            require_text(release_id, "release_id")
            return release_id
        active_release_id = self.active_release_id(domain_id=domain_id)
        if active_release_id is None:
            raise KeyError("active release is not set")
        return active_release_id


def _node_id_for_term(domain_id: str, term: object) -> str:
    typed_term = _as_evidence_term(term)
    text = typed_term.text
    concept_id = typed_term.concept_id
    if concept_id:
        return f"{domain_id}:concept:{concept_id}"
    return f"{domain_id}:term:{_normalise_key(text)}"


def _term_properties(term: object) -> dict[str, str]:
    typed_term = _as_evidence_term(term)
    properties = {"text": typed_term.text}
    concept_id = typed_term.concept_id
    original_text = typed_term.original_text
    if concept_id:
        properties["concept_id"] = concept_id
    if original_text:
        properties["original_text"] = original_text
    return properties


def _as_evidence_term(term: object) -> EvidenceTerm:
    if not isinstance(term, EvidenceTerm):
        raise TypeError("Expected EvidenceTerm")
    return term


def _normalise_key(value: str) -> str:
    return "-".join(value.casefold().split()) or "blank"


class Neo4jGraphRepository(InMemoryGraphRepository):
    """Neo4j writer adapter with the same read surface as the baseline repository.

    The Neo4j Python driver is intentionally injected instead of imported here so
    this module does not add a hard dependency before deployment wiring exists.
    """

    def __init__(self, *, driver: Any, database: str | None = None) -> None:
        super().__init__()
        self._driver = driver
        self._database = database

    def write_release(
        self,
        release: GraphRelease,
        assertions: tuple[EvidenceAssertion, ...],
        *,
        source_documents: tuple[SourceDocument, ...] = (),
        source_chunks: tuple[SourceChunk, ...] = (),
    ) -> None:
        super().write_release(
            release,
            assertions,
            source_documents=source_documents,
            source_chunks=source_chunks,
        )
        session_kwargs = {"database": self._database} if self._database else {}
        session_factory = self._driver.session
        with session_factory(**session_kwargs) as session:
            try:
                execute_write = session.execute_write
            except AttributeError:
                execute_write = session.write_transaction
            execute_write(
                _write_release_to_neo4j,
                release,
                self.list_assertions_for_release(
                    domain_id=release.domain_id,
                    release_id=release.id,
                ),
                source_documents,
                source_chunks,
            )


def _write_release_to_neo4j(
    tx: Any,
    release: GraphRelease,
    assertions: tuple[EvidenceAssertion, ...],
    source_documents: tuple[SourceDocument, ...],
    source_chunks: tuple[SourceChunk, ...],
) -> None:
    run = tx.run
    run(
        """
        MERGE (release:GraphRelease {domain_id: $domain_id, release_id: $release_id})
        SET release.version = $version,
            release.schema_version = $schema_version,
            release.index_version = $index_version,
            release.active = $active
        """,
        {
            "domain_id": release.domain_id,
            "release_id": release.id,
            "version": release.version,
            "schema_version": release.schema_version,
            "index_version": release.index_version,
            "active": release.active,
        },
    )
    for document in source_documents:
        run(
            """
            MERGE (document:SourceDocument {domain_id: $domain_id, document_id: $document_id})
            SET document.title = $title,
                document.source_uri = $source_uri,
                document.source_quality_tier = $source_quality_tier
            WITH document
            MATCH (release:GraphRelease {domain_id: $domain_id, release_id: $release_id})
            MERGE (release)-[:CITES_DOCUMENT]->(document)
            """,
            {
                "domain_id": release.domain_id,
                "release_id": release.id,
                "document_id": document.id,
                "title": document.title,
                "source_uri": document.source_uri,
                "source_quality_tier": document.source_quality_tier.value,
            },
        )
    chunks_by_id = {chunk.id: chunk for chunk in source_chunks}
    for chunk in source_chunks:
        run(
            """
            MERGE (chunk:SourceChunk {domain_id: $domain_id, chunk_id: $chunk_id})
            SET chunk.document_id = $document_id,
                chunk.locator = $locator,
                chunk.text = $text,
                chunk.parser_version = $parser_version
            WITH chunk
            MATCH (document:SourceDocument {domain_id: $domain_id, document_id: $document_id})
            MERGE (document)-[:HAS_CHUNK]->(chunk)
            """,
            {
                "domain_id": release.domain_id,
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "locator": chunk.locator.as_reference(),
                "text": chunk.text,
                "parser_version": chunk.parser_version,
            },
        )
    for assertion in assertions:
        subject_node_id = _node_id_for_term(release.domain_id, assertion.subject)
        object_node_id = _node_id_for_term(release.domain_id, assertion.object)
        parameters: dict[str, Any] = {
            "domain_id": release.domain_id,
            "release_id": release.id,
            "assertion_id": assertion.id,
            "subject_node_id": subject_node_id,
            "subject_label": assertion.subject.type.value,
            "subject_text": assertion.subject.text,
            "subject_concept_id": assertion.subject.concept_id,
            "object_node_id": object_node_id,
            "object_label": assertion.object.type.value,
            "object_text": assertion.object.text,
            "object_concept_id": assertion.object.concept_id,
            "predicate": assertion.predicate.value,
            "review_status": assertion.review_status.value,
            "direction": assertion.direction.value,
            "source_chunk_ids": list(assertion.source_chunk_ids),
        }
        run(
            """
            MERGE (subject:Concept {domain_id: $domain_id, node_id: $subject_node_id})
            SET subject.label = $subject_label,
                subject.text = $subject_text,
                subject.concept_id = $subject_concept_id
            MERGE (object:Concept {domain_id: $domain_id, node_id: $object_node_id})
            SET object.label = $object_label,
                object.text = $object_text,
                object.concept_id = $object_concept_id
            MERGE (assertion:EvidenceAssertion {
                domain_id: $domain_id,
                release_id: $release_id,
                assertion_id: $assertion_id
            })
            SET assertion.predicate = $predicate,
                assertion.review_status = $review_status,
                assertion.direction = $direction,
                assertion.source_chunk_ids = $source_chunk_ids
            MERGE (subject)-[:ASSERTS_SUBJECT_OF]->(assertion)
            MERGE (assertion)-[:ASSERTS_OBJECT]->(object)
            WITH assertion
            MATCH (release:GraphRelease {domain_id: $domain_id, release_id: $release_id})
            MERGE (release)-[:INCLUDES_ASSERTION]->(assertion)
            """,
            parameters,
        )
        for chunk_id in assertion.source_chunk_ids:
            if chunk_id not in chunks_by_id:
                continue
            run(
                """
                MATCH (assertion:EvidenceAssertion {
                    domain_id: $domain_id,
                    release_id: $release_id,
                    assertion_id: $assertion_id
                })
                MATCH (chunk:SourceChunk {domain_id: $domain_id, chunk_id: $chunk_id})
                MERGE (assertion)-[:SUPPORTED_BY]->(chunk)
                """,
                {
                    "domain_id": release.domain_id,
                    "release_id": release.id,
                    "assertion_id": assertion.id,
                    "chunk_id": chunk_id,
                },
            )
