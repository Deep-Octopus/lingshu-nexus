# ADR 0007: Graph Retrieval Baseline

## Status

Accepted

## Context

T-060 needs the first queryable graph and retrieval path after review release.
Project rules require user retrieval to read only active published releases and
never candidate-only data. The repository currently has no production database
driver wiring, and adding Neo4j GraphRAG, vector stores, or GraphRAG engines
would add network/dependency risk before a measurable evaluation set exists.

## Decision

- Extend `GraphRepository` around release-local published graph nodes,
  relationships, source documents, source chunks, and an explicit active release
  pointer.
- Keep a deterministic `InMemoryGraphRepository` as the executable baseline for
  tests and local development.
- Add `Neo4jGraphRepository` as an optional adapter that accepts an externally
  constructed Neo4j driver and writes the same release-local graph shape with
  Cypher. The module does not import the Neo4j SDK directly, so deployment can
  add the driver without making core business code depend on it.
- Add `RetrievalService` as the read-only user retrieval port. It syncs the
  current active `ReleaseRecord`, then searches only approved or
  conflict-reviewed assertions included in that active release.
- Use lexical search over assertion fields plus cited chunk text for the first
  baseline. Retrieval results must include source document and chunk locator
  references; assertions without resolvable chunk locators are withheld from the
  user search result.
- Defer vector retrieval, Neo4j GraphRAG for Python, LightRAG, and other
  GraphRAG engines until T-120 has fixed evaluation queries and can demonstrate
  recall or quality improvement.

## Consequences

- T-060 is fully testable without running Neo4j or downloading new packages.
- Candidate extraction rows cannot leak into retrieval because `RetrievalService`
  has no candidate repository dependency and reads only synced release snapshots.
- Switching the active release changes user retrieval immediately after sync
  while historical releases remain addressable by release id in the graph
  repository.
- Lexical retrieval is a baseline, not the final ranking strategy. It will miss
  semantic paraphrases until vector or GraphRAG retrieval is introduced behind
  the same `RetrievalService` port.

## T-120 Review (2026-06-15)

T-120 now provides fixed fixture queries, boundary cases, and an end-to-end
acceptance regression. This set proves active-release filtering, citation
integrity, candidate isolation, Skill routing, and rollback, but it is synthetic
and cannot measure real-domain semantic recall or answer quality.

Because authorized real literature and expert-reviewed citation expectations are
still unavailable, there is no evidence that a vector retriever or additional
GraphRAG engine would improve V1 enough to justify a new dependency. The lexical
baseline remains the V1 implementation. Re-evaluate this decision only after the
real T-120 benchmark can compare recall, citation accuracy, latency, cost, and
operational complexity on the same corpus.
