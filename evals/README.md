# V1 Evaluation Assets

This directory contains deterministic, fixture-only assets for T-120 regression
testing. They prove the platform boundaries and workflow mechanics; they are not
real clinical evidence and must not be reported as acupuncture or tVNS findings.

## Structure

- `fixtures/`: synthetic Markdown documents used by offline tests.
- `expected/`: structured extraction fixtures consumed by the fake provider.
- `questions/`: mentor-derived tVNS/taVNS evaluation seeds. Seeds marked
  `seed_only` require real literature and expert citation expectations before
  they become a formal domain benchmark.
- `boundary/`: evidence-insufficient, conflict, prompt-injection, and scope
  boundary cases.
- `terminology/`: deterministic normalization cases for known translation and
  semantic-confusion risks.

## Run

```bash
uv run python scripts/run_v1_acceptance.py
```

The command runs the fixed backend regression set and the frontend production
build. Use `--backend-only` only when Node.js is unavailable; that reduced run is
not the full local V1 acceptance command.

Real-material acceptance remains blocked until authorized local PDF/Markdown
files, expert-reviewed expected citations, and a usable MiMo configuration are
provided.
