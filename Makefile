# Quality gates for every part of Nest. `make check` is the single entry point.

.PHONY: install-app check check-changed check-daemon check-web check-apple fmt test install tokens icon app run-app

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

check: check-daemon check-web check-apple

# The gates of only the parts changed since the merge base with BASE, uncommitted and
# untracked files included (`nestd gates changed` prints why). If the parts cannot be worked
# out, every gate runs.
check-changed:
	@parts="$$(cd daemon && uv run nestd gates changed --base '$(BASE)')" || { \
	  echo "check-changed: could not work out the changed parts, running every gate"; \
	  parts="daemon web apple"; \
	}; \
	for part in $$parts; do $(MAKE) --no-print-directory check-$$part || exit 1; done

check-daemon:
	cd daemon && uv run ruff format --check .
	cd daemon && uv run ruff check .
	cd daemon && uv run pyright
	cd daemon && uv run pytest -n $(PYTEST_WORKERS)
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
	cd daemon && uv run pytest -n $(PYTEST_WORKERS)
	cd web && npm run test:coverage
	cd apple && swift test

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
