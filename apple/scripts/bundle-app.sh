#!/bin/sh
# Builds the release executable and assembles a signed apple/build/Nest.app.
# It signs with the local "Nest Local Signing" certificate when the login keychain has
# it, or with "Harness Local Signing", made before the rename to Nest (B43), so the
# Keychain keeps trusting the app across builds (D042); otherwise ad hoc.
set -eu

cd "$(dirname "$0")/.."

swift build -c release --product NestApp
bin_path="$(swift build -c release --show-bin-path)"

app="build/Nest.app"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin_path/NestApp" "$app/Contents/MacOS/Nest"
cp support/Info.plist "$app/Contents/Info.plist"
cp support/AppIcon.icns "$app/Contents/Resources/AppIcon.icns"
plutil -lint "$app/Contents/Info.plist" >/dev/null
identities="$(security find-identity -v -p codesigning)"
identity="-"
for name in "Nest Local Signing" "Harness Local Signing"; do
    if echo "$identities" | grep -q "\"$name\""; then
        identity="$name"
        break
    fi
done
codesign --force --sign "$identity" "$app"

echo "Built $(pwd)/$app"
