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
