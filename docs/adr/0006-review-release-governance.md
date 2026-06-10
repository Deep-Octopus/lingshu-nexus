# ADR 0006: Review and Release Governance

## Status

Accepted

## Context

T-050 turns candidate extraction output into published knowledge. Project rules
require candidate data, review decisions, published releases, and derived graph
indexes to remain logically separate. Medical assertions must not become
official knowledge only because a model generated them or because a source has a
high quality signal.

## Decision

- Add a `ReviewReleaseService` behind a repository port. The service owns
  terminology-backed normalization candidates, manual review decisions, release
  preview, release creation, activation, and rollback.
- Keep `CandidateExtractionRun` immutable after extraction. Review creates a
  separate reviewed assertion copy with lineage metadata and decision history.
- Load the initial acupuncture/tVNS terminology seed for deterministic
  normalization suggestions. tVNS/taVNS and stimulation-site aliases can be
  suggested automatically while retaining original wording; sensitive
  disease/symptom terms such as `depression`, `blues`, and `Postpartum blues`
  remain `needs_review` and are not automatically merged.
- Allow conflict-reviewed assertions to be publishable alongside approved
  assertions. The conflict marker is retained in assertion metadata and the
  review status remains visible in release previews.
- Require release assertions to have source chunks, a review decision, and
  extraction lineage covering candidate run, provider, model, prompt version,
  schema version, and parser version.
- Store release snapshots as immutable `DataLayer.PUBLISHED` artifacts. Candidate
  artifacts stay in `DataLayer.CANDIDATE`.

## Consequences

- Unreviewed candidate assertions cannot enter a release even if their schema is
  valid.
- Reviewers can approve, reject, modify, or mark conflicts without overwriting
  the original candidate extraction record.
- Rollback is implemented by changing the active release pointer while keeping
  historical release snapshots queryable.
- Actual reviewer account assignment and RBAC enforcement remain for T-110; T-050
  records actor strings and audit events so the flow is testable without
  external account data.
