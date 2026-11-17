#!/usr/bin/env bash
# `make release`: everything of one release in release/out/<version>/, built on this Mac,
# the Linux apps in Docker. Nothing is published. NEST_RELEASE_PARTS picks what to build,
# by default "daemon macos linux/arm64 linux/amd64"; a partial run leaves the other files
# of that folder alone.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
# The Mac app is signed with the Developer ID and notarized with the notarytool profile,
# both only in this Mac's login Keychain (B156).
team="Y46V894D78"
identity="$(security find-identity -v -p codesigning | grep -o -m 1 "Developer ID Application: .* ($team)" || true)"
notary_profile="nest-notary"
version="$(tr -d '[:space:]' < VERSION)"
notes="release/notes/$version.md"
out="release/out/$version"
parts="${NEST_RELEASE_PARTS:-daemon macos linux/arm64 linux/amd64}"
wants() { [[ " $parts " == *" $1 "* ]]; }

tree="$(release/check_clean.sh)"
commit="$(git rev-parse HEAD)"

(cd daemon && uv run --locked python ../release/set_version.py --check) || {
  echo "release: versions differ (run make version) or daemon/uv.lock is stale" >&2
  exit 1
}
[[ -f "$notes" ]] || { echo "release: write $notes first" >&2; exit 1; }
if wants macos; then
  # macOS keeps an installed Nest's permissions for one team only. Falling back would make
  # every user grant them again, so a missing certificate stops the release (D163).
  security find-identity -v -p codesigning | grep -q "\"$identity\"" || {
    echo "release: no Developer ID Application certificate for team $team in the keychain" >&2
    exit 1
  }
  xcrun notarytool history --keychain-profile "$notary_profile" >/dev/null || {
    echo "release: the notarytool profile \"$notary_profile\" does not work" >&2
    exit 1
  }
fi
# latest.json is signed at the end with the release key, only ever in this Keychain (D184).
(cd daemon && uv run --locked python ../release/release_key.py check)

# Apple checks the app and returns a ticket, stapled to it so it opens offline too. A
# ticket cannot be stapled to a zip, so the stapled app is zipped after (B156).
notarize() {
  local app="$1" upload="apple/build/Nest-notarize.zip" result id status
  rm -f "$upload"
  ditto -c -k --keepParent "$app" "$upload"
  result="$(xcrun notarytool submit "$upload" --keychain-profile "$notary_profile" --wait \
    --output-format json)" || true
  rm -f "$upload"
  id="$(plutil -extract id raw -o - - <<<"$result" 2>/dev/null)" || id=""
  status="$(plutil -extract status raw -o - - <<<"$result" 2>/dev/null)" || status=""
  if [[ "$status" != "Accepted" ]]; then
    echo "release: notarization ended with \"${status:-no answer}\": $result" >&2
    [[ -z "$id" ]] || xcrun notarytool log "$id" --keychain-profile "$notary_profile" >&2
    exit 1
  fi
  # Stapling checks the ticket it attaches. A separate `stapler validate` asks Apple again,
  # which can fail for a while right after the ticket appears.
  xcrun stapler staple "$app"
  [[ "$(spctl --assess --type execute -vv "$app" 2>&1)" == *"source=Notarized Developer ID"* ]] || {
    echo "release: Gatekeeper does not accept the notarized Nest.app" >&2
    exit 1
  }
}

# Each download also under a name without the version, so a link to
# releases/latest/download/<name> always gives the newest release.
latest() { ln -f "$out/$1" "$out/${1/-$version-/-}"; }

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
  codesign --verify --deep --strict apple/build/Nest.app
  signature="$(codesign -dvv apple/build/Nest.app 2>&1)"
  [[ "$signature" == *"Authority=$identity"* && "$signature" == *"TeamIdentifier=$team"* &&
    "$signature" == *"(runtime)"* ]] || {
    echo "release: Nest.app is not signed by $identity with the hardened runtime" >&2
    exit 1
  }
  notarize apple/build/Nest.app
  rm -f "$out/Nest-$version-macos-arm64.zip"
  ditto -c -k --keepParent apple/build/Nest.app "$out/Nest-$version-macos-arm64.zip"
  latest "Nest-$version-macos-arm64.zip"
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
  latest "Nest-$version-linux-$arch.AppImage"
  latest "Nest-$version-linux-$arch.deb"
done

cp release/install.sh "$out/install.sh"
# The build can take hours (notarization), so the tree is checked again: an edit or commit
# made meanwhile would ship under the start commit's manifest (B159 R54).
[[ "$(release/check_clean.sh)" == "$tree" && "$(git rev-parse HEAD)" == "$commit" ]] || {
  echo "release: the code changed during the build (HEAD was $commit), build again" >&2
  exit 1
}
(cd daemon && uv run --locked python ../release/make_manifest.py "$root/$out" "$version" "$root/$notes" \
  "$(tr -d '[:space:]' < "$root/release/uv-version")" "$commit" "$tree")
echo "release: $out"
ls -la "$out"
