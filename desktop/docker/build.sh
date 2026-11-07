#!/usr/bin/env bash
# Builds and tests the Linux desktop app in Docker, so no Rust toolchain is needed on the
# host. Usage: desktop/docker/build.sh [test|lint|fmt|build|bundle|lock|shell]
#   test    cargo test
#   lint    cargo fmt --check and cargo clippy
#   fmt     cargo fmt
#   build   tauri build --debug --no-bundle; the binary lands in desktop/target/linux-<arch>/
#   bundle  tauri build (release .deb and AppImage) into desktop/target/linux-<arch>/bundle/
#   lock    refresh src-tauri/Cargo.lock
#   shell   a shell in the build container
# Build the web first (cd web && npm run build) for a binary with the real UI; without
# web/dist/desktop.html a placeholder page is bundled. NEST_DOCKER_PLATFORM picks the
# platform (default linux/arm64).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
desktop="$(dirname "$here")"
repo="$(dirname "$desktop")"
platform="${NEST_DOCKER_PLATFORM:-linux/arm64}"
arch="${platform#linux/}"
image="nest-desktop-build:$arch-$(shasum "$here/Dockerfile" | cut -c1-12)"
command="${1:-test}"

if ! docker image inspect "$image" >/dev/null 2>&1; then
  docker build --platform "$platform" -t "$image" "$here"
fi

# The UI bundled into the binary: the web build when there is one, else a placeholder.
if [[ -f "$repo/web/dist/desktop.html" && "$command" != test && "$command" != lint ]]; then
  frontend='{}'
else
  frontend='{"build":{"frontendDist":"/tmp/placeholder-ui"}}'
fi

script='set -e
mkdir -p /tmp/placeholder-ui
printf "<!doctype html><title>Nest</title><p>Build the web UI first.</p>" > /tmp/placeholder-ui/desktop.html
cd /work/desktop/src-tauri
tauri() { (cd /work/desktop && { [ -x node_modules/.bin/tauri ] || npm ci --no-audit --no-fund; } && node_modules/.bin/tauri "$@"); }
out=/work/desktop/target/linux-'"$arch"'
case "$0" in
  test) cargo test --locked ;;
  lint) cargo fmt --check && cargo clippy --locked --all-targets -- -D warnings ;;
  fmt) cargo fmt ;;
  build)
    tauri build --debug --no-bundle --config "$TAURI_CONFIG"
    mkdir -p "$out/debug" && cp /target/debug/nest-desktop "$out/debug/"
    echo "binary: desktop/target/linux-'"$arch"'/debug/nest-desktop" ;;
  bundle)
    tauri build --config "$TAURI_CONFIG"
    mkdir -p "$out" && rm -rf "$out/bundle" && cp -r /target/release/bundle "$out/"
    echo "bundles: desktop/target/linux-'"$arch"'/bundle" ;;
  lock) cargo generate-lockfile ;;
  shell) exec bash ;;
  *) echo "unknown command: $0" >&2; exit 2 ;;
esac'

tty=()
[[ -t 0 && -t 1 ]] && tty=(-it)
exec docker run --rm ${tty[@]+"${tty[@]}"} --platform "$platform" \
  -v "$repo:/work" \
  -v nest-desktop-cargo-registry:/opt/cargo/registry \
  -v "nest-desktop-target-$arch:/target" \
  -v "nest-desktop-node-modules-$arch:/work/desktop/node_modules" \
  -e CARGO_TARGET_DIR=/target \
  -e TAURI_CONFIG="$frontend" \
  "$image" bash -c "$script" "$command"
