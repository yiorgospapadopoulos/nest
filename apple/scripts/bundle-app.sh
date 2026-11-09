#!/bin/sh
# Builds the release executable and assembles a signed apple/build/Nest.app.
# It signs with the local "Nest Local Signing" certificate when the login keychain has
# it, or with "Harness Local Signing", made before the rename to Nest (B43), so the
# Keychain keeps trusting the app across builds (D042); otherwise ad hoc. A release sets
# NEST_SIGNING_IDENTITY: that certificate or nothing.
set -eu

cd "$(dirname "$0")/.."

swift build -c release --product NestApp
swift build -c release --product NestComputer
bin_path="$(swift build -c release --show-bin-path)"

app="build/Nest.app"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin_path/NestApp" "$app/Contents/MacOS/Nest"
cp support/Info.plist "$app/Contents/Info.plist"
# A developer build names its checkout, for the line that repairs its service (B130). A
# release names nothing: no path of this machine ships.
if [ -z "${NEST_SIGNING_IDENTITY:-}" ]; then
    plutil -insert NestCheckout -string "$(cd .. && pwd)" "$app/Contents/Info.plist"
fi
# The icon (B95): macOS draws the light or dark tile from the Assets.car compiled out of
# support/AppIcon.icon (CFBundleIconName); the .icns from `make icon` stays the plain icon
# file (CFBundleIconFile) and replaces the one actool writes. actool exits 0 even when it
# fails, so the catalog is checked for.
xcrun actool support/AppIcon.icon --compile "$app/Contents/Resources" --app-icon AppIcon \
    --platform macosx --minimum-deployment-target 26.0 --target-device mac \
    --include-all-app-icons --enable-on-demand-resources NO \
    --output-partial-info-plist /dev/null >/dev/null
test -f "$app/Contents/Resources/Assets.car"
cp support/AppIcon.icns "$app/Contents/Resources/AppIcon.icns"
plutil -lint "$app/Contents/Info.plist" >/dev/null
# The computer use helper (B150): its own app inside Nest.app, so macOS gives it its own
# Accessibility and Screen Recording entries. It takes the app's version.
helper="$app/Contents/Helpers/Nest Computer.app"
mkdir -p "$helper/Contents/MacOS"
cp "$bin_path/NestComputer" "$helper/Contents/MacOS/NestComputer"
cp support/NestComputer-Info.plist "$helper/Contents/Info.plist"
for key in CFBundleShortVersionString CFBundleVersion; do
    plutil -replace "$key" -string "$(plutil -extract "$key" raw support/Info.plist)" \
        "$helper/Contents/Info.plist"
done
plutil -lint "$helper/Contents/Info.plist" >/dev/null
identities="$(security find-identity -v -p codesigning)"
identity="-"
for name in ${NEST_SIGNING_IDENTITY:+"$NEST_SIGNING_IDENTITY"} "Nest Local Signing" "Harness Local Signing"; do
    if echo "$identities" | grep -q "\"$name\""; then
        identity="$name"
        break
    fi
    if [ -n "${NEST_SIGNING_IDENTITY:-}" ]; then
        echo "The certificate \"$name\" is not in the keychain" >&2
        exit 1
    fi
done
# The helper is signed first, then the app around it (no --deep).
codesign --force --sign "$identity" "$helper"
codesign --force --sign "$identity" "$app"

echo "Built $(pwd)/$app"
