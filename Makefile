# Quality gates for every part of harness. `make check` is the single entry point.

.PHONY: install-app check check-daemon check-web check-apple fmt test install tokens app run-app

# Swift sources to format and lint; the generated tokens follow the generator's layout.
APPLE_SWIFT = $$(find apple/Sources apple/Tests -name '*.swift' -not -path '*/Generated/*') apple/Package.swift

install:
	cd daemon && uv sync
	cd web && npm ci

check: check-daemon check-web check-apple

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

check-apple:
	swift format lint --strict --parallel $(APPLE_SWIFT)
	cd apple && swift build
	apple/scripts/coverage.sh

fmt:
	cd daemon && uv run ruff format . && uv run ruff check --fix .
	cd web && npm run format
	swift format --in-place --parallel $(APPLE_SWIFT)

test:
	cd daemon && uv run pytest
	cd web && npm run test:coverage
	cd apple && swift test

tokens:
	cd daemon && uv run harness design generate

# The Mac app as an ad-hoc signed bundle in apple/build/Harness.app.
app:
	apple/scripts/bundle-app.sh

run-app: app
	open apple/build/Harness.app

# Copy the built app into /Applications so it opens from Spotlight, Launchpad and the Dock.
install-app: app
	rm -rf /Applications/Harness.app
	ditto apple/build/Harness.app /Applications/Harness.app
	# Leave one Harness for Spotlight and Launchpad: the installed copy.
	/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u apple/build/Harness.app
	rm -rf apple/build/Harness.app
	@echo "Installed /Applications/Harness.app"
