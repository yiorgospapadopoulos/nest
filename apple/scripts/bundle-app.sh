#!/bin/sh
# Builds the release executable and assembles an ad-hoc signed apple/build/Harness.app.
set -eu

cd "$(dirname "$0")/.."

swift build -c release --product HarnessApp
bin_path="$(swift build -c release --show-bin-path)"

app="build/Harness.app"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin_path/HarnessApp" "$app/Contents/MacOS/harness"
cp support/Info.plist "$app/Contents/Info.plist"
plutil -lint "$app/Contents/Info.plist" >/dev/null
codesign --force --sign - "$app"

echo "Built $(pwd)/$app"
