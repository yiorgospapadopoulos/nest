# Quality gates for every part of harness. `make check` is the single entry point.

.PHONY: check check-daemon check-web fmt test install tokens

install:
	cd daemon && uv sync
	cd web && npm ci

check: check-daemon check-web

check-daemon:
	cd daemon && uv run ruff format --check .
	cd daemon && uv run ruff check .
	cd daemon && uv run pyright
	cd daemon && uv run pytest
	cd daemon && uv run pip-audit --skip-editable

check-web:
	cd web && npm run format:check
	cd web && npm run lint
	cd web && npm run typecheck
	cd web && npm run test:coverage
	cd web && npm run build
	cd web && npm run audit

fmt:
	cd daemon && uv run ruff format . && uv run ruff check --fix .
	cd web && npm run format

test:
	cd daemon && uv run pytest
	cd web && npm run test:coverage

tokens:
	cd daemon && uv run harness design generate
