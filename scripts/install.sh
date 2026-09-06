#!/usr/bin/env bash
# Ramanujan installer (macOS / Linux) — like `npm i -g pi`, plus the engine.
#
#   curl -fsSL <url>/install.sh | bash
#   # or from a checkout:
#   ./scripts/install.sh
#
# Does, in order:
#   1. checks node>=22, npm, python>=3.12
#   2. builds the agent workspace (tsgo, same as `npm run build`)
#   3. installs ONLY the `ramanujan` bin globally (direct launcher shim —
#      never `npm link`, which would shadow the genuine pi package/bins
#      because this fork keeps pi's package name for merge-ability)
#   4. installs `ramanujan-engine` on PATH (uv tool > pipx > pip --user)
#   5. verifies both binaries; never touches ~/.config/ramanujan
#      and never touches an existing pi install (~/.pi, `pi` bin).
#
# First `ramanujan` launch with an empty config opens the setup wizard
# (provider → live models → main_model → worktree preset). Skip it with
# RAMANUJAN_NO_SETUP=1.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log() { printf '==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- 1. prerequisites -------------------------------------------------------
command -v node >/dev/null || die "node not found — install Node 22+ first"
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 22 ] || die "node >= 22 required (found $(node -v))"
command -v npm >/dev/null || die "npm not found"
command -v python3 >/dev/null || die "python3 not found"
PY_MINOR="$(python3 -c 'import sys; print(sys.version_info.minor)')"
PY_MAJOR="$(python3 -c 'import sys; print(sys.version_info.major)')"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 12 ]; }; then
  die "python >= 3.12 required (found $(python3 --version))"
fi
log "node $(node -v), npm $(npm -v), $(python3 --version)"

# --- 2. build agent workspace ------------------------------------------------
log "building agent workspace…"
(
  cd "$REPO_ROOT/agent"
  npm install
  npm run build
)

# --- 3. global `ramanujan` bin (shim, never npm link) -------------------------
# NOTE: this fork intentionally keeps pi's package name for merge-ability, so
# `npm link` / `npm install -g <tarball>` would shadow a genuine pi install
# (same package dir, same `pi` bin). Instead install a tiny launcher that
# execs this checkout's bundle directly: zero interference with pi.
log "installing ramanujan bin globally…"
# Undo an old `npm link` of this fork (same package name would shadow a
# genuine pi install: same package dir, same `pi` bin). Only removes the link
# when it points inside THIS repo — never touches a genuine pi install —
# then restores genuine pi from the registry.
GLOBAL_PKG="$(npm root -g)/@earendil-works/pi-coding-agent"
if [ -L "$GLOBAL_PKG" ]; then
  LINK_TARGET="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$GLOBAL_PKG")"
  case "$LINK_TARGET" in
    "$REPO_ROOT"/*)
      log "removing stale self-link that shadows genuine pi…"
      rm -f "$GLOBAL_PKG"
      GLOBAL_BIN="$(npm root -g)/../bin"
      [ ! -L "$GLOBAL_BIN/pi" ] || rm -f "$GLOBAL_BIN/pi"
      [ ! -L "$GLOBAL_BIN/ramanujan" ] || rm -f "$GLOBAL_BIN/ramanujan"
      if npm i -g @earendil-works/pi-coding-agent; then
        log "genuine pi restored ($(command -v pi))"
      else
        log "WARNING: could not restore genuine pi — run manually: npm i -g @earendil-works/pi-coding-agent"
      fi
      ;;
  esac
fi
BUNDLE="$REPO_ROOT/agent/packages/coding-agent/dist/bundle/cli.js"
[ -f "$BUNDLE" ] || die "bundle missing at $BUNDLE (build step failed?)"
BIN_DIR="$(npm root -g)/../bin"
mkdir -p "$BIN_DIR"
# NOTE: extensionless bin files run as CommonJS, so no top-level await here.
node -e 'require("fs").writeFileSync(process.argv[2], "#!/usr/bin/env node\nimport(" + JSON.stringify(process.argv[3]) + ").catch((e) => { console.error(e); process.exit(1); });\n")' _ "$BIN_DIR/ramanujan" "$BUNDLE"
chmod +x "$BIN_DIR/ramanujan"
command -v ramanujan >/dev/null || die "ramanujan bin not on PATH after install (check npm global bin dir)"
if [ -n "$(command -v pi 2>/dev/null || true)" ] && [ "$(command -v ramanujan)" = "$(command -v pi)" ]; then
  die "ramanujan resolved to the pi bin — refusing to shadow pi"
fi
log "pi bin untouched: $(command -v pi 2>/dev/null || echo '(pi not installed)')"

# --- 4. engine on PATH --------------------------------------------------------
install_engine_uv() {
  command -v uv >/dev/null || return 1
  (cd "$REPO_ROOT" && uv tool install --force .)
}
install_engine_pipx() {
  command -v pipx >/dev/null || return 1
  pipx install --force "$REPO_ROOT"
}
install_engine_pip() {
  python3 -m pip install --user "$REPO_ROOT" 2>/dev/null \
    || python3 -m pip install --user --break-system-packages "$REPO_ROOT"
}
if command -v ramanujan-engine >/dev/null; then
  log "ramanujan-engine already on PATH ($(command -v ramanujan-engine))"
else
  log "installing ramanujan-engine…"
  if install_engine_uv; then
    log "engine installed via uv tool"
  elif install_engine_pipx; then
    log "engine installed via pipx"
  elif install_engine_pip; then
    log "engine installed via pip --user (ensure ~/.local/bin is on PATH)"
  else
    die "could not install ramanujan-engine (tried uv tool, pipx, pip --user)"
  fi
fi

# --- 5. verify -----------------------------------------------------------------
log "verifying…"
ramanujan --version
ramanujan-engine --help >/dev/null
log "engine OK ($(command -v ramanujan-engine))"

if [ -f "$HOME/.config/ramanujan/config.toml" ]; then
  log "existing config kept at ~/.config/ramanujan/config.toml"
else
  log "no config yet — first 'ramanujan' launch opens the setup wizard"
fi
log "done. Run: ramanujan"
