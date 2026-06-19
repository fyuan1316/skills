#!/usr/bin/env bash
# hami-dev L0 bootstrap — provision the Go toolchain + build caches for the
# HAMi tech stack onto the BIG ephemeral disk, leaving source on the small
# persistent volume untouched.
#
# Why this exists: the devpod's persistent volume (/workspaces) has ~1G free,
# far too little for Go's module + build cache, but the container overlay (/)
# has >200G. The catch: overlay is ephemeral (wiped on pod restart) and only
# /tmp is writable on it. So we put the toolchain + caches under /tmp and make
# this script idempotent + cheap to re-run after a pod restart.
#
# Idempotent: re-running with the toolchain already present is a no-op (a few
# version checks). Safe to source the emitted env.sh from any shell or skill.
#
# Usage:
#   bash bootstrap.sh                 # provision (default toolroot /tmp/hami-toolchain)
#   source $(bash bootstrap.sh --print-env)   # provision then get env path
#   TOOLROOT=/tmp/x GO_VERSION=go1.26.4 bash bootstrap.sh
set -euo pipefail

TOOLROOT="${TOOLROOT:-/tmp/hami-toolchain}"
# go.mod across the HAMi repos requires `go 1.26.2`; install >= that.
GO_VERSION="${GO_VERSION:-go1.26.4}"
GO_ARCH="${GO_ARCH:-linux-amd64}"
ENV_FILE="$TOOLROOT/env.sh"

log() { echo "hami-bootstrap: $*" >&2; }

mkdir -p "$TOOLROOT"

# --- Go toolchain -----------------------------------------------------------
need_go=1
if [ -x "$TOOLROOT/go/bin/go" ]; then
  have="$("$TOOLROOT/go/bin/go" version 2>/dev/null | awk '{print $3}')"
  if [ "$have" = "$GO_VERSION" ]; then
    log "Go $have already present, skipping download"
    need_go=0
  else
    log "Go version drift (have $have, want $GO_VERSION); reinstalling"
    rm -rf "$TOOLROOT/go"
  fi
fi

if [ "$need_go" = "1" ]; then
  tarball="${GO_VERSION}.${GO_ARCH}.tar.gz"
  log "downloading $tarball ..."
  curl -fsSL "https://go.dev/dl/${tarball}" -o "$TOOLROOT/$tarball"
  log "extracting to $TOOLROOT/go ..."
  rm -rf "$TOOLROOT/go"
  tar -C "$TOOLROOT" -xzf "$TOOLROOT/$tarball"
  rm -f "$TOOLROOT/$tarball"
fi

# --- caches on big disk -----------------------------------------------------
mkdir -p "$TOOLROOT/gopath" "$TOOLROOT/gocache"

# --- emit a sourceable env --------------------------------------------------
cat > "$ENV_FILE" <<EOF
# sourced by hami-dev skill; relocates Go + caches onto the big ephemeral disk
export GOROOT="$TOOLROOT/go"
export GOPATH="$TOOLROOT/gopath"
export GOCACHE="$TOOLROOT/gocache"
export GOMODCACHE="$TOOLROOT/gopath/pkg/mod"
export PATH="$TOOLROOT/go/bin:$TOOLROOT/gopath/bin:\$PATH"
# China network: uncomment if go.dev module proxy is slow/blocked
# export GOPROXY=https://goproxy.cn,direct
EOF

# shellcheck disable=SC1090
. "$ENV_FILE"
log "ready: $(go version) | GOPATH=$GOPATH GOCACHE=$GOCACHE"
log "source it:  source $ENV_FILE"

# --print-env: print the env file path on stdout (everything else is stderr)
if [ "${1:-}" = "--print-env" ]; then echo "$ENV_FILE"; fi
