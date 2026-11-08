#!/usr/bin/env bash
# `make release`: everything of one release in release/out/<version>/, built on this Mac,
# the Linux apps in Docker. Nothing is published. NEST_RELEASE_PARTS picks what to build,
# by default "daemon macos linux/arm64 linux/amd64"; a partial run leaves the other files
# of that folder alone.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
identity="Nest Local Signing"
version="$(tr -d '[:space:]' < VERSION)"
notes="release/notes/$version.md"
out="release/out/$version"
parts="${NEST_RELEASE_PARTS:-daemon macos linux/arm64 linux/amd64}"
wants() { [[ " $parts " == *" $1 "* ]]; }

(cd daemon && uv run python ../release/set_version.py --check) || {
  echo "release: versions differ, run make version" >&2
  exit 1
}
[[ -f "$notes" ]] || { echo "release: write $notes first" >&2; exit 1; }
# Every installed Nest trusts this one certificate. Falling back would make macOS ask each
# user for every permission again, so a missing certificate stops the release (D163).
security find-identity -v -p codesigning | grep -q "\"$identity\"" || {
  echo "release: no Developer ID Application certificate for team $team in the keychain" >&2
  exit 1
}

mkdir -p "$out"
(cd web && npm ci --no-audit --no-fund && npm run build)

if wants daemon; then
  rm -rf daemon/src/nestd/web_dist
  trap 'rm -rf "$root/daemon/src/nestd/web_dist"' EXIT
  cp -R web/dist daemon/src/nestd/web_dist
  (cd daemon && uv build --wheel --out-dir "$root/$out")
  rm -rf daemon/src/nestd/web_dist
  rm -f "$out/.gitignore"
  (cd daemon && uv export --frozen --no-dev --no-emit-project --format requirements.txt \
    --output-file "$root/$out/nestd-$version-requirements.txt" --quiet)
fi

if wants macos; then
  NEST_SIGNING_IDENTITY="$identity" apple/scripts/bundle-app.sh
  signature="$(codesign -dvv apple/build/Nest.app 2>&1)"
  [[ "$signature" == *"Authority=$identity"* ]] || {
    echo "release: Nest.app is not signed by $identity" >&2
    exit 1
  }
  rm -f "$out/Nest-$version-macos-arm64.zip"
  ditto -c -k --keepParent apple/build/Nest.app "$out/Nest-$version-macos-arm64.zip"
fi

for platform in linux/arm64 linux/amd64; do
  wants "$platform" || continue
  docker_arch="${platform#linux/}"
  case "$docker_arch" in amd64) arch=x86_64; deb=amd64 ;; *) arch=arm64; deb=arm64 ;; esac
  NEST_DOCKER_PLATFORM="$platform" desktop/docker/build.sh bundle
  bundle="desktop/target/linux-$docker_arch/bundle"
  # The build volume keeps earlier versions' bundles, so only this version's are copied.
  cp "$bundle"/appimage/*"_${version}_"*.AppImage "$out/Nest-$version-linux-$arch.AppImage"
  cp "$bundle"/deb/*"_${version}_$deb.deb" "$out/Nest-$version-linux-$arch.deb"
done

cp release/install.sh "$out/install.sh"
(cd daemon && uv run python ../release/make_manifest.py "$root/$out" "$version" "$root/$notes" \
  "$(tr -d '[:space:]' < "$root/release/uv-version")")
echo "release: $out"
ls -la "$out"
