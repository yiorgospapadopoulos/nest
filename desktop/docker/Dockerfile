# Build and test environment for the Linux desktop app (linux/arm64 or amd64).
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev \
      libayatana-appindicator3-dev librsvg2-dev ca-certificates pkg-config xz-utils \
    && rm -rf /var/lib/apt/lists/*

ARG NODE_VERSION=22.23.4
RUN arch="$(dpkg --print-architecture)"; case "$arch" in arm64) n=arm64 ;; amd64) n=x64 ;; *) exit 1 ;; esac; \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${n}.tar.xz" \
      | tar -xJ -C /usr/local --strip-components=1

ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo PATH=/opt/cargo/bin:$PATH
RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable \
      --component clippy,rustfmt --no-modify-path

# Tauri fetches this plugin only when it is missing. An AppImage's magic bytes stop it running
# under emulation (amd64 on Apple silicon), and with no FUSE here each one unpacks itself.
ENV APPIMAGE_EXTRACT_AND_RUN=1
RUN arch="$(uname -m)"; plugin=/root/.cache/tauri/linuxdeploy-plugin-appimage.AppImage; \
    mkdir -p "$(dirname "$plugin")"; \
    curl -fsSL -o "$plugin" "https://github.com/linuxdeploy/linuxdeploy-plugin-appimage/releases/download/continuous/linuxdeploy-plugin-appimage-${arch}.AppImage"; \
    printf '\0\0\0' | dd of="$plugin" bs=1 seek=8 count=3 conv=notrunc; \
    chmod +x "$plugin"

WORKDIR /work/desktop
