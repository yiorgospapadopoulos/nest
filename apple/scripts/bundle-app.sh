#!/bin/sh
# Builds the release executable and assembles a signed apple/build/Harness.app.
# It signs with the local "Harness Local Signing" certificate when the login keychain has
# it, so the Keychain keeps trusting the app across builds (D042); otherwise ad hoc.
set -eu

cd "$(dirname "$0")/.."

swift build -c release --product HarnessApp
bin_path="$(swift build -c release --show-bin-path)"

app="build/Harness.app"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin_path/HarnessApp" "$app/Contents/MacOS/harness"
cp support/Info.plist "$app/Contents/Info.plist"
cp support/AppIcon.icns "$app/Contents/Resources/AppIcon.icns"
plutil -lint "$app/Contents/Info.plist" >/dev/null
identity="Harness Local Signing"
if security find-identity -v -p codesigning | grep -q "\"$identity\""; then
    codesign --force --sign "$identity" "$app"
else
    codesign --force --sign - "$app"
fi

echo "Built $(pwd)/$app"
