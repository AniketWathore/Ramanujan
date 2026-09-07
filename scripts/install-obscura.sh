#!/usr/bin/env bash
# Install bundled Obscura binary for Ramanujan literature agent.
# Prefers prebuilt release (70MB, instant) over cargo build (5min V8 compile).
# Keeps obscura + obscura-worker together as required by README:165.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$REPO_ROOT/tools/obscura/bin"
OBSCURA_BIN="$BIN_DIR/obscura"
WORKER_BIN="$BIN_DIR/obscura-worker"
VERSION="0.1.0"  # obscura-main Cargo.toml workspace.package.version
log(){ printf '==> obscura: %s\n' "$*"; }
# Already installed?
if [ -x "$OBSCURA_BIN" ]; then
  log "already present at $OBSCURA_BIN ($($OBSCURA_BIN --version 2>/dev/null || echo ok))"
  exit 0
fi
mkdir -p "$BIN_DIR"
# Detect platform for prebuilt archive
OS="$(uname -s)"; ARCH="$(uname -m)"
case "$OS-$ARCH" in
  Darwin-arm64|Darwin-aarch64) SUFFIX="aarch64-macos" ;;
  Darwin-x86_64)               SUFFIX="x86_64-macos" ;;
  Linux-x86_64|Linux-x86-64)   SUFFIX="x86_64-linux" ;;
  Linux-aarch64|Linux-arm64)  SUFFIX="aarch64-linux" ;;
  *) SUFFIX="" ;;
esac
# Try prebuilt download — minimal no-render (smallest, ~30MB vs 70MB render) is enough for literature text
if [ -n "$SUFFIX" ]; then
  # Minimal literature needs only fetch --dump text/markdown + JS (no screenshot/PDF) → -no-render
  URL="https://github.com/h4ckf0r0day/obscura/releases/latest/download/obscura-${SUFFIX}-no-render.tar.gz"
  log "trying prebuilt minimal $URL"
  if command -v curl >/dev/null && curl -fsSL --max-time 30 "$URL" -o /tmp/obscura.tar.gz 2>/dev/null; then
    tar xzf /tmp/obscura.tar.gz -C "$BIN_DIR" 2>/dev/null || tar xzf /tmp/obscura.tar.gz -C /tmp && cp /tmp/obscura* "$BIN_DIR"/ 2>/dev/null || true
    chmod +x "$BIN_DIR"/obscura* 2>/dev/null || true
    if [ -x "$OBSCURA_BIN" ]; then
      log "installed prebuilt minimal $( $OBSCURA_BIN --version 2>/dev/null || echo $SUFFIX-no-render )"
      exit 0
    fi
  fi
  # Fallback to full render prebuilt if minimal not found
  URL="https://github.com/h4ckf0r0day/obscura/releases/latest/download/obscura-${SUFFIX}.tar.gz"
  log "trying prebuilt full $URL"
  if command -v curl >/dev/null && curl -fsSL --max-time 30 "$URL" -o /tmp/obscura.tar.gz 2>/dev/null; then
    tar xzf /tmp/obscura.tar.gz -C "$BIN_DIR" 2>/dev/null || tar xzf /tmp/obscura.tar.gz -C /tmp && cp /tmp/obscura* "$BIN_DIR"/ 2>/dev/null || true
    chmod +x "$BIN_DIR"/obscura* 2>/dev/null || true
    if [ -x "$OBSCURA_BIN" ]; then
      log "installed prebuilt $( $OBSCURA_BIN --version 2>/dev/null || echo $SUFFIX )"
      exit 0
    fi
  fi
  log "prebuilt not available for $SUFFIX — falling back to cargo build"
fi
# Cargo build from vendor source
if ! command -v cargo >/dev/null; then
  log "cargo not found and no prebuilt for $OS-$ARCH — literature will use arXiv fallback until obscura is installed"
  exit 0
fi
log "building minimal from source (no-render, smallest)…"
# Use vendor source if present, else obscura-main checkout
SRC="$REPO_ROOT/vendor/obscura"
[ -d "$SRC" ] || SRC="$REPO_ROOT/obscura-main"
[ -d "$SRC" ] || { log "no source at $SRC"; exit 0; }
CARGO_INCREMENTAL=0 cargo build --release -p obscura-cli --bins --no-default-features --manifest-path "$SRC/Cargo.toml"
cp "$SRC/target/release/obscura" "$OBSCURA_BIN"
cp "$SRC/target/release/obscura-worker" "$WORKER_BIN" 2>/dev/null || true
chmod +x "$BIN_DIR"/obscura*
log "built $OBSCURA_BIN"
