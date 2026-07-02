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

# ── subcommands ───────────────────────────────────────────────────────────────
case "${1:-up}" in
  stop)  docker stop "$CONTAINER" 2>/dev/null && echo "Stopped $CONTAINER." || echo "Not running."; exit 0 ;;
  logs)  docker logs -f "$CONTAINER"; exit 0 ;;
esac

# ── 1. Docker present? ────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  cat <<'EOF'
Docker is not installed. Install it once (needs sudo), then re-run this script:

    sudo apt update && sudo apt install -y docker.io
    sudo systemctl enable --now docker
    sudo usermod -aG docker "$USER"     # then log out/in so `docker` works without sudo

If you prefer not to install Docker, skip this — Ultron's deep research still
works via the Tavily/DuckDuckGo links in the chain; SearXNG just makes it
fully keyless and unlimited.
EOF
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but the daemon isn't reachable as this user."
  echo "Run:  sudo systemctl start docker   (and ensure you're in the 'docker' group)"
  exit 1
fi

# ── 2. Write the settings.yml that enables the JSON API + disables the limiter ─
mkdir -p "$DIR"
if [ ! -f "$SETTINGS" ]; then
  SECRET="$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(32))')"
  cat > "$SETTINGS" <<EOF
# Minimal SearXNG config for Ultron. Overrides the image defaults.
use_default_settings: true
server:
  secret_key: "${SECRET}"   # required by SearXNG
  limiter: false             # CRITICAL: allow local programmatic (JSON) requests
  image_proxy: false
search:
  safe_search: 0
  formats:
    - html
    - json                   # CRITICAL: without this, ?format=json returns an error
EOF
  echo "Wrote $SETTINGS (JSON API enabled, limiter off)."
else
  echo "Using existing $SETTINGS"
fi

# ── 3. (Re)launch the container ───────────────────────────────────────────────
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
echo "Starting SearXNG on http://localhost:${PORT} ..."
docker run -d --name "$CONTAINER" --restart unless-stopped \
  -p "127.0.0.1:${PORT}:8080" \
  -v "${DIR}:/etc/searxng:rw" \
  searxng/searxng:latest >/dev/null

# ── 4. Wait for it, then verify the JSON endpoint actually works ──────────────
echo -n "Waiting for SearXNG to come up"
for i in $(seq 1 30); do
  if curl -fsS "http://localhost:${PORT}/healthz" >/dev/null 2>&1 \
     || curl -fsS "http://localhost:${PORT}/" >/dev/null 2>&1; then break; fi
  echo -n "."; sleep 1
done
echo

echo "Testing the JSON API (this is what Ultron uses)..."
JSON="$(curl -fsS "http://localhost:${PORT}/search?q=hello+world&format=json" 2>/dev/null || true)"
if echo "$JSON" | grep -q '"results"'; then
  N="$(echo "$JSON" | python3 -c 'import sys,json;print(len(json.load(sys.stdin).get("results",[])))' 2>/dev/null || echo "?")"
  echo "✅ SearXNG JSON API works — returned ${N} results."
  echo "   Ultron will use it automatically (SEARXNG_URL=http://localhost:${PORT})."
  echo "   You are now keyless: deep research works without Tavily."
else
  echo "⚠️  SearXNG is running but the JSON API didn't return results yet."
  echo "    Give it ~20s (first run initializes engines), then test:"
  echo "    curl 'http://localhost:${PORT}/search?q=test&format=json'"
  echo "    If it stays empty, check:  bash setup_searxng.sh logs"
fi
