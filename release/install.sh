#!/bin/sh
# Installs Nest: curl -fsSL <address>/install.sh | sh
# Run it again to repair an install. Everything is checked before anything changes, and the
# whole script sits in `main`, so a cut-off download runs nothing.
set -eu

RELEASE_URL="${NEST_RELEASE_URL:-https://github.com/yiorgospapadopoulos/nest/releases/latest/download}"
MAC_APP="${NEST_MAC_APP:-/Applications/Nest.app}"
MACOS_MINIMUM=26

say() { printf '%s\n' "$*"; }
stop() {
    printf 'Nest: %s\n' "$*" >&2
    exit 1
}

work=""
partial=""
clean_up() {
    [ -z "$work" ] || rm -rf "$work"
    [ -z "$partial" ] || rm -rf "$partial"
}

check_machine() {
    case "$(uname -s)" in
    Darwin)
        system=macos
        [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = 1 ] ||
            stop "Nest needs an Apple silicon Mac. Intel Macs aren't supported."
        major="$(sw_vers -productVersion | cut -d. -f1)"
        [ "$major" -ge "$MACOS_MINIMUM" ] ||
            stop "Nest needs macOS $MACOS_MINIMUM or later. This Mac has $(sw_vers -productVersion)."
        [ -w "$(dirname "$MAC_APP")" ] ||
            stop "This account can't write to $(dirname "$MAC_APP"). Run this from an administrator account."
        platform=macos-arm64
        data="${NEST_DATA_DIR:-$HOME/Library/Application Support/nest}"
        unit="$HOME/Library/LaunchAgents/com.nest.daemon.plist"
        ;;
    Linux)
        system=linux
        case "$(uname -m)" in
        x86_64) platform=linux-x86_64 ;;
        aarch64 | arm64) platform=linux-arm64 ;;
        *) stop "Nest runs on x86_64 and arm64 Linux. This computer is $(uname -m)." ;;
        esac
        systemctl --user show-environment >/dev/null 2>&1 ||
            stop "Nest needs a systemd user session (systemctl --user), and this computer doesn't have one."
        share="${XDG_DATA_HOME:-$HOME/.local/share}"
        data="${NEST_DATA_DIR:-$share/nest}"
        unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/nest.service"
        ;;
    *)
        stop "Nest runs on macOS and Linux for now. This computer runs $(uname -s)."
        ;;
    esac
}

# A service that starts anything else is a developer's own install, which this would break.
check_not_developer_install() {
    [ -f "$unit" ] || return 0
    grep -qF "$data/daemon/current/bin/python" "$unit" && return 0
    stop "A Nest service already runs from somewhere else ($unit). Nothing was changed."
}

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1
    fi
}

# The one line of latest.json for a kind of file and a platform.
entry() {
    grep -F "\"platform\": \"$2\", \"kind\": \"$1\"" "$work/latest.json" | head -n 1
}

field() {
    printf '%s\n' "$1" | sed -n "s/.*\"$2\": \"\([^\"]*\)\".*/\1/p"
}

fetch() { # kind platform destination
    line="$(entry "$1" "$2")"
    name="$(field "$line" name)"
    [ -n "$name" ] || stop "This release has no $1 for $2."
    case "$name" in
    http://* | https://*) address="$name" ;;
    *) address="$RELEASE_URL/$name" ;;
    esac
    curl -fsSL --retry 2 -o "$3" "$address" || stop "Could not download $name."
    [ "$(sha256_of "$3")" = "$(field "$line" sha256)" ] ||
        stop "$name didn't match its checksum, so nothing was installed. Try again."
}

fetch_release() {
    curl -fsSL --retry 2 -o "$work/latest.json" "$RELEASE_URL/latest.json" ||
        stop "Could not reach $RELEASE_URL. Check your connection and try again."
    version="$(sed -n 's/^  "version": "\(.*\)",$/\1/p' "$work/latest.json")"
    [ -n "$version" ] || stop "The release list could not be read."
    say "Installing Nest $version"
    fetch app "$platform" "$work/app"
    fetch wheel any "$work/nestd.whl"
    fetch requirements any "$work/requirements.txt"
}

find_uv() {
    if command -v uv >/dev/null 2>&1; then
        uv="$(command -v uv)"
    elif [ -x "$data/bin/uv" ]; then
        uv="$data/bin/uv"
    else
        fetch uv "$platform" "$work/uv.tar.gz"
        mkdir -p "$work/uv"
        tar -xzf "$work/uv.tar.gz" -C "$work/uv"
        mkdir -p "$data/bin"
        cp "$work"/uv/*/uv "$data/bin/uv"
        uv="$data/bin/uv"
    fi
}

# The daemon in a folder of its own, made beside the others and renamed once it runs.
build_daemon() {
    say "Setting up the background service"
    folder="$data/daemon/$version"
    partial="$folder.partial"
    rm -rf "$partial"
    mkdir -p "$data/daemon"
    export UV_PYTHON_INSTALL_DIR="$data/bin/python"
    export UV_CACHE_DIR="$work/uv-cache"
    "$uv" venv --quiet --relocatable --python 3.12 --python-preference only-managed "$partial"
    "$uv" pip install --quiet --python "$partial/bin/python" --require-hashes -r "$work/requirements.txt"
    # uv reads the version from the name, and engine updates install this copy again.
    wheel="$partial/$(field "$(entry wheel any)" name)"
    cp "$work/nestd.whl" "$wheel"
    "$uv" pip install --quiet --python "$partial/bin/python" --no-deps "$wheel"
    # Kept for Undo update, and for an app that has to swap to this version's copy.
    cp "$work/app" "$partial/app-file"
    "$partial/bin/python" -m nestd service --help >/dev/null ||
        stop "The downloaded daemon doesn't run on this computer."
    rm -rf "$folder.old"
    [ ! -d "$folder" ] || mv "$folder" "$folder.old"
    mv "$partial" "$folder"
    partial=""
    rm -rf "$folder.old"
    ln -sfn "$version" "$data/daemon/current"
    python="$data/daemon/current/bin/python"
}

install_mac_app() {
    mkdir "$work/app-new"
    ditto -x -k "$work/app" "$work/app-new"
    rm -rf "$MAC_APP.old"
    [ ! -d "$MAC_APP" ] || mv "$MAC_APP" "$MAC_APP.old"
    ditto "$work/app-new/Nest.app" "$MAC_APP"
    rm -rf "$MAC_APP.old"
    opener="open"
    app_path="$MAC_APP"
}

# An AppImage runs through FUSE, which newer Ubuntu leaves out. Unpacked it needs none.
needs_unpacking() {
    ! { ldconfig -p 2>/dev/null | grep -q 'libfuse\.so\.2'; }
}

install_linux_app() {
    folder="$data/app"
    mkdir -p "$folder"
    chmod +x "$work/app"
    (cd "$work" && ./app --appimage-extract >/dev/null)
    cp "$work/app" "$folder/.Nest.AppImage.new"
    mv "$folder/.Nest.AppImage.new" "$folder/Nest.AppImage"
    rm -rf "$folder/Nest.AppDir"
    app_path="$folder/Nest.AppImage"
    if needs_unpacking; then
        mv "$work/squashfs-root" "$folder/Nest.AppDir"
        app_path="$folder/Nest.AppDir/AppRun"
        icons="$folder/Nest.AppDir/usr/share/icons/hicolor"
    else
        icons="$work/squashfs-root/usr/share/icons/hicolor"
    fi
    share="${XDG_DATA_HOME:-$HOME/.local/share}"
    mkdir -p "$share/icons/hicolor" "$share/applications"
    cp -R "$icons/." "$share/icons/hicolor/"
    {
        printf '[Desktop Entry]\nType=Application\nName=Nest\n'
        printf 'Comment=Nest, a personal coding-agent manager\n'
        printf 'Exec="%s"\nIcon=nest-desktop\n' "$app_path"
        printf 'Categories=Development;\nStartupWMClass=nest-desktop\nTerminal=false\n'
    } >"$share/applications/nest.desktop"
    opener="linux"
}

link_command() {
    mkdir -p "$HOME/.local/bin"
    ln -sfn "$data/daemon/current/bin/nest" "$HOME/.local/bin/nest"
}

# `nestd serve` stops at start without the Secret Service, and the guide comes from the
# daemon, so this says why instead of leaving a window that never connects.
check_secret_service() {
    [ "$system" = linux ] || return 0
    timeout 30 "$python" -m nestd service check-secrets ||
        stop "Fix that, then run this line again."
}

start_service() {
    "$python" -m nestd service install >/dev/null
    "$python" -m nestd service wait ||
        stop "The background service didn't start. See $data/logs/daemon.log."
}

open_app() {
    if [ "$opener" = open ]; then
        open "$app_path"
    elif [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        nohup "$app_path" >/dev/null 2>&1 &
    fi
}

show_path_line() {
    case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *)
        say ""
        say "To use the nest command, add this to your shell's startup file:"
        say "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
    esac
}

main() {
    check_machine
    check_not_developer_install
    work="$(mktemp -d)"
    trap clean_up EXIT
    trap 'exit 130' INT TERM
    fetch_release
    find_uv
    build_daemon
    if [ "$system" = macos ]; then install_mac_app; else install_linux_app; fi
    link_command
    check_secret_service
    start_service
    open_app
    say "Nest $version is installed."
    show_path_line
}


main "$@" </dev/null
