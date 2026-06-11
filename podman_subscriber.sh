#!/bin/bash
# Thin wrapper around compose for the Kafka subscriber stack.
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
Kafka subscriber via compose

Usage: podman_subscriber.sh {preflight|up|down|logs|status|rebuild}

  preflight  Run infrastructure checks (one-shot)
  up         Preflight then start kafka-subscriber
  down       Stop subscriber stack
  logs       Follow subscriber logs
  status     Show service status
  rebuild    Rebuild images and restart subscriber
EOF
}

case "${1:-}" in
  preflight)
    compose run --rm preflight
    ;;
  up)
    compose run --rm preflight
    compose up -d kafka-subscriber
    ;;
  down)
    compose down
    ;;
  logs)
    compose logs -f kafka-subscriber
    ;;
  status)
    compose ps
    ;;
  rebuild)
    compose build kafka-subscriber
    compose run --rm preflight
    compose up -d --force-recreate kafka-subscriber
    ;;
  *)
    usage
    exit 1
    ;;
esac
