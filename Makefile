.PHONY: lint format-check typecheck test quality api worker web-dev

PYTHON ?= python3

lint:
	$(PYTHON) scripts/quality.py lint

format-check:
	$(PYTHON) scripts/quality.py format-check

typecheck:
	$(PYTHON) scripts/quality.py typecheck

test:
	$(PYTHON) -m unittest discover -s tests

quality: lint format-check typecheck test

api:
	uv run uvicorn lingshu_nexus.api.main:app --host 0.0.0.0 --port 8000 --reload

worker:
	uv run python -m lingshu_nexus.worker.main

web-dev:
	npm --prefix frontend run dev

