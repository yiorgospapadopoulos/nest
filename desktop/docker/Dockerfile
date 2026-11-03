# Build and test environment for the Linux desktop app (linux/arm64 or amd64).
FROM ubuntu:24.04
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

WORKDIR /work/desktop
