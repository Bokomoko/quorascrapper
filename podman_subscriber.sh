#!/bin/bash
# qsbk backend stack: Kafka subscriber + HTTP serve (Chrome extension API).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

ensure_runtime() {
  if command -v podman >/dev/null 2>&1; then
    if podman info >/dev/null 2>&1; then
      return 0
    fi
    echo "Podman is installed but not running. Starting podman machine…" >&2
    if podman machine start; then
      echo "Podman machine started." >&2
      return 0
    fi
    echo "Could not start Podman. Try manually:" >&2
    echo "  podman machine start" >&2
    exit 1
  fi

  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    return 0
  fi

  cat >&2 <<'EOF'
No container runtime is running.

macOS with Podman (recommended):
  brew install podman
  podman machine start
  ./podman_qsbk.sh up

Or start Docker Desktop, then rerun this script.
EOF
  exit 1
}

compose() {
  ensure_runtime
  if command -v podman >/dev/null 2>&1; then
    podman compose "$@"
    return
  fi
  docker compose "$@"
}

STACK_SERVICES=(kafka-subscriber qsbk-serve)

usage() {
  cat <<'EOF'
qsbk container stack (subscriber + serve)

Usage: podman_subscriber.sh {preflight|up|down|logs|status|rebuild|remote} [serve|subscriber]

  remote      Deploy/run stack on bokomint (see deploy_bokomint.sh)

  preflight   Run Kafka + Mongo checks (one-shot)
  up          Preflight, then start subscriber + qsbk serve
  down        Stop stack
  logs        Follow logs (both services, or one: logs serve / logs subscriber)
  status      Show service status
  rebuild     Rebuild image and recreate stack

Local dev: serve listens on host :8765 (network_mode: host on Linux).
Production: use ./deploy_bokomint.sh up — extension → http://bokomint.local:8765

Requires Podman (brew install podman) or Docker. On macOS: podman machine start
EOF
}

case "${1:-}" in
  preflight)
    compose run --rm preflight
    ;;
  up)
    compose run --rm preflight
    compose up -d "${STACK_SERVICES[@]}"
    echo ""
    echo "qsbk stack running (local):"
    echo "  serve       http://127.0.0.1:8765/ping  (host network on Linux)"
    echo "  subscriber  Kafka → MongoDB"
    echo "Reload the Chrome extension; Kafka output enables when serve is online."
    ;;
  down)
    compose down
    ;;
  logs)
    shift || true
    case "${1:-}" in
      serve) targets=(qsbk-serve) ;;
      subscriber) targets=(kafka-subscriber) ;;
      "") targets=(kafka-subscriber qsbk-serve) ;;
      *) echo "Unknown service: $1" >&2; exit 1 ;;
    esac
    compose logs -f "${targets[@]}"
    ;;
  status)
    compose ps
    ;;
  rebuild)
    compose build kafka-subscriber qsbk-serve
    compose run --rm preflight
    compose up -d --force-recreate "${STACK_SERVICES[@]}"
    ;;
  remote)
    shift || true
    exec "$(dirname "$0")/deploy_bokomint.sh" "$@"
    ;;
  *)
    usage
    exit 1
    ;;
esac
