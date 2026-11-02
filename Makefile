# Quality gates for every part of Nest. `make check` is the single entry point.

.PHONY: install-app check check-changed gates check-daemon check-web check-apple fmt test install tokens icon app run-app \
	lint-daemon test-daemon audit-daemon lint-web test-web audit-web lint-apple test-apple audit-apple coverage

# Swift sources to format and lint; the generated tokens follow the generator's layout.
APPLE_SWIFT = $$(find apple/Sources apple/Tests -name '*.swift' -not -path '*/Generated/*') apple/Package.swift

# Daemon test worker processes for the gates (B99). Four are as fast as one per core on the
# M4 Air's 4 performance cores and leave room for other gates; `PYTEST_WORKERS=auto` uses
# every core and `PYTEST_WORKERS=0` one process. Targeted pytest runs stay single-process.
PYTEST_WORKERS ?= 4

# What `make check-changed` compares against (B100): the merge base of this ref and HEAD.
BASE ?= main

install:
	cd daemon && uv sync
	cd web && npm ci
	# The open engines' pinned versions in Nest's own folder (B107); quick once there.
	cd daemon && uv run nestd engines install

# Each part's gate is three stages: lint (format, lint, types), test (tests and build) and
# audit. Across parts the fast stages run first, so a lint failure shows in seconds (B111).
check:
	$(MAKE) --no-print-directory gates PARTS="daemon web apple"

# The gates of only the parts changed since the merge base with BASE, uncommitted and
# untracked files included (`nestd gates changed` prints why). If the parts cannot be worked
# out, every gate runs.
check-changed:
	@parts="$$(cd daemon && uv run nestd gates changed --base '$(BASE)')" || { \
	  echo "check-changed: could not work out the changed parts, running every gate"; \
	  parts="daemon web apple"; \
	}; \
	$(MAKE) --no-print-directory gates PARTS="$$parts"

# A passing run's times, each stage per part, go to gate-times.jsonl in Nest's data folder
# (NEST_DATA_DIR when set) for Settings > Performance (B115); a failure to record is only
# reported.
NOW_MS = perl -MTime::HiRes=time -e 'printf "%d", time * 1000'

gates:
	@started=$$($(NOW_MS)); times=""; \
	for stage in lint test audit; do \
	  for part in $(PARTS); do \
	    stage_started=$$($(NOW_MS)); \
	    $(MAKE) --no-print-directory $$stage-$$part || exit 1; \
	    times="$$times $$part=$$(( $$($(NOW_MS)) - stage_started ))"; \
	  done; \
	done; \
	total=$$(( $$($(NOW_MS)) - started )); \
	[ -z "$$times" ] || (cd daemon && uv run nestd gates record --total $$total $$times) \
	  || echo "gates: could not record the gate times"

check-daemon: lint-daemon test-daemon audit-daemon
check-web: lint-web test-web audit-web
check-apple: lint-apple test-apple

lint-daemon:
	cd daemon && uv run ruff format --check .
	cd daemon && uv run ruff check .
	cd daemon && uv run pyright

test-daemon:
	cd daemon && uv run pytest -n $(PYTEST_WORKERS)

audit-daemon:
	cd daemon && uv run pip-audit --skip-editable

lint-web:
	cd web && npm run format:check
	cd web && npm run lint
	cd web && npm run typecheck

# The bundle only: `typecheck` has already run tsc.
test-web:
	cd web && npm test
	cd web && npx vite build

audit-web:
	cd web && npm run audit

lint-apple:
	swift format lint --strict --parallel $(APPLE_SWIFT)

# One build of the app, NestKit and the tests, then the tests on it. A coverage build uses
# other flags and rebuilds everything, so coverage stays out of the gate (`make coverage`).
test-apple:
	cd apple && swift build --build-tests
	cd apple && swift test --skip-build

audit-apple:
	@:

# Coverage of every part, reported and never a target (D131); not part of the gates (B111).
coverage:
	cd daemon && uv run pytest -n $(PYTEST_WORKERS) --cov=nestd --cov-branch --cov-report=term-missing
	cd web && npm run test:coverage
	apple/scripts/coverage.sh

fmt:
	cd daemon && uv run ruff format . && uv run ruff check --fix .
	cd web && npm run format
	swift format --in-place --parallel $(APPLE_SWIFT)

test: test-daemon test-web test-apple

tokens:
	cd daemon && uv run nestd design generate

# The app icon from the icon pixie's sprite (B95): the PNG sources, then AppIcon.icns from the
# Mac source at every size the Finder asks for. The appearance-aware icon is compiled from
# apple/support/AppIcon.icon when the app is bundled.
icon:
	cd daemon && uv run nestd design icon
	rm -rf apple/build/AppIcon.iconset && mkdir -p apple/build/AppIcon.iconset
	for size in 16 32 128 256 512; do \
	  sips -z $$size $$size apple/support/AppIcon-1024.png --out apple/build/AppIcon.iconset/icon_$${size}x$${size}.png >/dev/null; \
	  sips -z $$((size * 2)) $$((size * 2)) apple/support/AppIcon-1024.png --out apple/build/AppIcon.iconset/icon_$${size}x$${size}@2x.png >/dev/null; \
	done
	iconutil -c icns apple/build/AppIcon.iconset -o apple/support/AppIcon.icns
	rm -rf apple/build/AppIcon.iconset

# The Mac app bundle in apple/build/Nest.app, signed with "Nest Local Signing" when present, ad hoc otherwise (D042).
app:
	apple/scripts/bundle-app.sh

run-app: app
	open apple/build/Nest.app

# Copy the built app into /Applications so it opens from Spotlight, Launchpad and the Dock.
# The app from before the rename to Nest (B43), Harness.app, is removed; its settings and
# backgrounds are copied by Nest on its first launch.
install-app: app
	rm -rf /Applications/Nest.app
	ditto apple/build/Nest.app /Applications/Nest.app
	-/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u /Applications/Harness.app
	rm -rf /Applications/Harness.app
	# Leave one Nest for Spotlight and Launchpad: the installed copy. The build copy may never
	# have been registered (lsregister -10814), so a failure here is ignored.
	-/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u apple/build/Nest.app
	rm -rf apple/build/Nest.app
	@echo "Installed /Applications/Nest.app"
