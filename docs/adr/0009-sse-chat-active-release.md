# ADR 0009: SSE Chat over Active Published Releases

Date: 2026-06-12

## Status

Accepted

## Context

T-080 requires a researcher-facing web chat that streams answer progress, shows
the Skill and active release used, expands citations, handles missing evidence
clearly, and never reads unreviewed candidate knowledge.

## Decision

The V1 chat baseline uses FastAPI `StreamingResponse` with Server-Sent Events.
The stream emits `retrieval`, `text`, `citation`, `done`, and `error` events.
The chat route delegates answer generation to `SkillRegistryService`, which in
turn uses `RetrievalService` over the indexed active release. No LLM is invoked
in this baseline and no candidate repository is available to chat.

Chat sessions, messages, and feedback have in-memory runtime adapters for local
tests. SQL migration `0007_chat_sessions` defines the future PostgreSQL tables
for sessions, messages, citation keys, release metadata, and feedback.

The Vue page provides a single `/chat`-style workspace as the first screen:
Skill selection, streaming answer text, citation side panel, clear failure
states, active release metadata, and useful/not useful/correction feedback.

## Consequences

- HTTP SSE is enough for one-way answer streaming and is easier to audit than a
  bidirectional WebSocket channel for V1.
- Answers are deterministic summaries from approved evidence fixtures until a
  later task introduces a governed chat LLM adapter.
- Missing active release or missing evidence produces explicit limitation text
  instead of fabricated conclusions.
- Feedback is captured as product data but does not alter evidence or releases.
