#!/usr/bin/env bash
# A release is built from committed code only (B159 R54): it is signed and shipped as built,
# and the public repository gets the committed files only. Refuses any change to a tracked
# file, and new files where the build reads them; new files elsewhere (plans, scratch) may
# stay. Ignored files where the build reads them are refused too, as the wheel backend and
# Vite read them all the same; only caches and the build's own outputs may be there.
# Prints "clean", or "dirty" when NEST_RELEASE_ALLOW_DIRTY=1 lets a test build go on.
set -euo pipefail

cd "$(dirname "$0")/.."
inputs=(daemon web apple desktop design release VERSION Makefile)
# What the wheel, the web build, the Mac app and the Linux app read. `:(glob)` keeps `*`
# within one folder, so web/node_modules is not walked.
built=(
  daemon/src daemon/pyproject.toml
  web/src web/build web/public ':(glob)web/*.html' ':(glob)web/*.ts' ':(glob)web/*.json'
  ':(glob)web/.env*'
  apple/Sources apple/support apple/scripts apple/Package.swift apple/Package.resolved
  desktop/package.json desktop/package-lock.json desktop/src-tauri/src
  desktop/src-tauri/capabilities desktop/src-tauri/icons desktop/src-tauri/build.rs
  desktop/src-tauri/Cargo.lock ':(glob)desktop/src-tauri/*.toml' ':(glob)desktop/src-tauri/*.json'
)
# Python caches, Finder's files and the web build that build.sh copies in for the wheel.
caches='(^|/)__pycache__/|(^|/)\.DS_Store$|^daemon/src/nestd/web_dist/'
changes="$(
  git status --porcelain --untracked-files=no
  git status --porcelain --untracked-files=all -- "${inputs[@]}" | grep '^??' || true
  git ls-files --others --ignored --exclude-standard -- "${built[@]}" | grep -Ev "$caches" |
    sed 's/^/ignored: /' || true
)"
if [[ -z "$changes" ]]; then
  echo clean
  exit 0
fi
if [[ "${NEST_RELEASE_ALLOW_DIRTY:-}" == 1 ]]; then
  echo "release: building uncommitted changes for a test, the manifest says so" >&2
  echo dirty
  exit 0
fi
{
  echo "release: commit these changes first, as a release is built from committed code only:"
  echo "$changes"
  echo "For a test build only, put NEST_RELEASE_ALLOW_DIRTY=1 in front of make release."
} >&2
exit 1
