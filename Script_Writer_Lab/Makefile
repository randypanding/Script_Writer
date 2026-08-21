.PHONY: ci lint test guard

lint:
	uv run ruff check src tests scripts

test:
	uv run pytest -q

guard:
	uv run python scripts/corpus_leak_guard.py

ci: lint test guard
