#!/bin/bash
# Thin wrapper around compose for on-demand scraper runs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

compose() {
  if command -v podman-compose >/dev/null 2>&1; then
    podman-compose "$@"
  elif podman compose version >/dev/null 2>&1; then
    podman compose "$@"
  else
    docker compose "$@"
  fi
}

usage() {
  cat <<'EOF'
Quora scraper via compose (on-demand)

Usage: podman_scraper.sh {preflight|run|build}

  preflight  Run scraper-mode infrastructure checks
  run        Preflight then run scraper once (profile: scraper)
  build      Build scraper image

Extra args after 'run' are passed to quora-scraper, e.g.:
  podman_scraper.sh run --sender stdout --max-results 5
EOF
}

case "${1:-}" in
  preflight)
    compose run --rm preflight uv run quora-preflight --mode scraper
    ;;
  build)
    compose --profile scraper build quora-scraper
    ;;
  run)
    shift
    compose run --rm preflight uv run quora-preflight --mode scraper
    compose --profile scraper run --rm quora-scraper uv run qsbk "$@"
    ;;
  *)
    usage
    exit 1
    ;;
esac
