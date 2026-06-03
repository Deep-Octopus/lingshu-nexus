# ADR 0002: Evidence Assertion Schema

## Status

Accepted

## Context

The platform needs to answer research questions with traceable medical evidence.
Plain triples such as `(taVNS) -[TREATS]-> (insomnia)` do not preserve study
population, intervention parameters, comparator, outcome direction, safety
signals, source quality, review state, or source chunk locator.

The first domain remains `acupuncture`. tVNS/taVNS is treated as a professional
sub-scenario through topic tags, terminology seeds, and parameter fields rather
than as a separate platform workflow.

## Decision

- Define shared domain dataclasses for `SourceDocument`, `SourceChunk`, `Study`,
  `CanonicalConcept`, `EvidenceAssertion`, `ReviewDecision`, and `GraphRelease`.
- Make `domain_id` mandatory on core objects.
- Require publishable `EvidenceAssertion` records to have source chunk ids and
  `review_status=approved`.
- Keep tVNS/taVNS terminology in versioned config, including cymba conchae,
  cavum conchae, tragus, depression, and blues mapping cautions.
- Store source quality signals as review and ranking metadata only; they do not
  become automatic evidence grades.

## Consequences

- Graph relations can still be derived for navigation, but medical answers must
  use reviewed evidence assertions.
- A second domain can be added by supplying a new `DomainConfig` and terminology
  config without rewriting core schema classes.
- Extraction prompts and review UI can evolve against the same schema contract.

