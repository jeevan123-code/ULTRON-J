#!/usr/bin/env bash
#
# setup_searxng.sh — stand up a local, keyless SearXNG for Ultron's deep research.
#
# WHY: Ultron's deep-research engine searches via a chain (Tavily → SearXNG → DDG).
# A self-hosted SearXNG is the only backend that is BOTH keyless AND not
# rate-limited — once it's running, you no longer depend on Tavily at all.
#
# THE CRITICAL BIT: SearXNG returns HTML by default. Ultron calls it with
# ?format=json, which only works if the JSON output format is enabled AND the
# bot limiter is off for local API calls. This script writes a settings.yml
# that does exactly that — the #1 reason "SearXNG is running but returns
# nothing".
#
# Ultron already reads SEARXNG_URL (default http://localhost:8080), so once this
# is up there is NO code change needed.
#
# Usage:   bash setup_searxng.sh
#          bash setup_searxng.sh stop      # stop the container
#          bash setup_searxng.sh logs      # tail logs
#
set -euo pipefail

CONTAINER="ultron-searxng"
PORT="8080"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/searxng"
SETTINGS="${DIR}/settings.yml"
SRC_DIR="${SEARXNG_SRC_DIR:-$HOME/searxng-src}"

# ── settings.yml — the same file either install path needs ────────────────────
write_settings() {
  mkdir -p "$DIR"
  if [ -f "$SETTINGS" ]; then
    echo "Using existing $SETTINGS"
    return
  fi
  local secret
  secret="$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(32))')"
  cat > "$SETTINGS" <<EOF
# Minimal SearXNG config for Ultron. Overrides the image defaults.
use_default_settings: true
server:
  secret_key: "${secret}"   # required by SearXNG
  limiter: false             # CRITICAL: allow local programmatic (JSON) requests
  image_proxy: false
  bind_address: "127.0.0.1"
  port: ${PORT}
search:
  safe_search: 0
  formats:
    - html
    - json                   # CRITICAL: without this, ?format=json returns an error
EOF
  echo "Wrote $SETTINGS (JSON API enabled, limiter off)."
}

# ── Verify the JSON endpoint — the only check that proves Ultron can use it ───
verify_json() {
  echo -n "Waiting for SearXNG to come up"
  for _ in $(seq 1 30); do
    if curl -fsS "http://localhost:${PORT}/healthz" >/dev/null 2>&1 \
       || curl -fsS "http://localhost:${PORT}/" >/dev/null 2>&1; then break; fi
    echo -n "."; sleep 1
  done
  echo

  echo "Testing the JSON API (this is what Ultron uses)..."
  local json n
  json="$(curl -fsS "http://localhost:${PORT}/search?q=hello+world&format=json" 2>/dev/null || true)"
  if echo "$json" | grep -q '"results"'; then
    n="$(echo "$json" | python3 -c 'import sys,json;print(len(json.load(sys.stdin).get("results",[])))' 2>/dev/null || echo "?")"
    echo "✅ SearXNG JSON API works — returned ${n} results."
    echo "   Ultron will use it automatically (SEARXNG_URL=http://localhost:${PORT})."
    echo "   To prefer it over the paid key, set in .env:"
    echo "     DEEP_SEARCH_ORDER=searxng,tavily,duckduckgo,wikipedia"
    return 0
  fi
  echo "⚠️  SearXNG is running but the JSON API didn't return results yet."
  echo "    Give it ~20s (first run initializes engines), then test:"
  echo "    curl 'http://localhost:${PORT}/search?q=test&format=json'"
  echo "    Almost always this means limiter/formats are wrong in ${SETTINGS}."
  return 1
}

# ── Docker-free path — SearXNG is a Python app, so run it from source ─────────
# Used on machines without Docker. Installing Docker needs sudo; this needs
# nothing but python3, and it is how this was actually brought up on
# 2026-07-30 (measured 24/24 afterwards, against the DDG scraper's 3/24).
source_up() {
  command -v python3 >/dev/null 2>&1 || { echo "python3 not found — cannot continue."; exit 1; }

  if [ ! -d "$SRC_DIR/.git" ]; then
    echo "Cloning SearXNG to $SRC_DIR ..."
    git clone --depth 1 -q https://github.com/searxng/searxng.git "$SRC_DIR"
  fi
  if [ ! -x "$SRC_DIR/.venv/bin/python" ]; then
    echo "Building venv (a few minutes the first time) ..."
    python3 -m venv "$SRC_DIR/.venv"
    "$SRC_DIR/.venv/bin/pip" install -q --upgrade pip setuptools wheel
    "$SRC_DIR/.venv/bin/pip" install -q -r "$SRC_DIR/requirements.txt"
  fi

  write_settings

  # Prefer a user service so it survives a reboot; fall back to nohup.
  local unit="$HOME/.config/systemd/user/searxng.service"
  if command -v systemctl >/dev/null 2>&1; then
    mkdir -p "$(dirname "$unit")"
    cat > "$unit" <<EOF
[Unit]
Description=SearXNG — local keyless search backend for Ultron
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${SRC_DIR}
Environment=SEARXNG_SETTINGS_PATH=${SETTINGS}
ExecStart=${SRC_DIR}/.venv/bin/python -m searx.webapp
Restart=on-failure
RestartSec=5
PrivateDevices=true
NoNewPrivileges=true

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now searxng
    echo "Started as a systemd user service (survives reboot)."
  else
    ( cd "$SRC_DIR" && SEARXNG_SETTINGS_PATH="$SETTINGS" \
        nohup .venv/bin/python -m searx.webapp >/tmp/searxng.log 2>&1 & )
    echo "Started with nohup — logs at /tmp/searxng.log (will NOT survive reboot)."
  fi
}

# ── subcommands ───────────────────────────────────────────────────────────────
case "${1:-up}" in
  stop)  docker stop "$CONTAINER" 2>/dev/null && echo "Stopped $CONTAINER." || echo "Not running."; exit 0 ;;
  logs)  docker logs -f "$CONTAINER"; exit 0 ;;
esac

# ── 1. Docker present? ────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not found — installing from source instead (no sudo needed)."
  echo "To use Docker instead: sudo apt install -y docker.io && sudo usermod -aG docker \"\$USER\""
  source_up
  verify_json
  exit $?
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but the daemon isn't reachable as this user."
  echo "Run:  sudo systemctl start docker   (and ensure you're in the 'docker' group)"
  exit 1
fi

# ── 2. Write the settings.yml that enables the JSON API + disables the limiter ─
write_settings

# ── 3. (Re)launch the container ───────────────────────────────────────────────
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
echo "Starting SearXNG on http://localhost:${PORT} ..."
docker run -d --name "$CONTAINER" --restart unless-stopped \
  -p "127.0.0.1:${PORT}:8080" \
  -v "${DIR}:/etc/searxng:rw" \
  searxng/searxng:latest >/dev/null

# ── 4. Wait for it, then verify the JSON endpoint actually works ──────────────
verify_json
