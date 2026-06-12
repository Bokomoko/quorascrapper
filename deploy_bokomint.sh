#!/bin/bash
# Sync repo to bokomint and run qsbk containers there (serve + subscriber).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

REMOTE_HOST="${QSBK_REMOTE_HOST:-bokomint.local}"
REMOTE_USER="${QSBK_REMOTE_USER:-${USER}}"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"
REMOTE_PATH="${QSBK_REMOTE_PATH:-~/quorascrapper}"
REMOTE_COMPOSE="${QSBK_REMOTE_COMPOSE:-podman-compose}"
STACK_SERVICES=(kafka-subscriber qsbk-serve)
IMAGE="quorascrapper-qsbk:latest"

RSYNC_EXCLUDES=(
  --exclude '.git'
  --exclude '__pycache__'
  --exclude '*.pyc'
  --exclude '.venv'
  --exclude 'scraper_output.jsonl'
  --exclude '.env'
  --exclude '.env.container'
  --exclude '.env.production'
  --exclude '.env.scraper'
)

usage() {
  cat <<EOF
Deploy qsbk stack on bokomint (Linux host, not local Mac).

Usage: deploy_bokomint.sh {sync|env|build|preflight|up|down|logs|status|rebuild|tunnel} [serve|subscriber]

  build       Build image only (streams logs; first run ~5–10 min)
  up          sync + build + preflight + start stack
  tunnel      SSH port-forward :8765 → bokomint (use when LAN blocks 8765)

  On bokomint (once, if curl from Mac times out):
    sudo ufw allow 8765/tcp

  Then Mac extension:
    qsbk install --serve-url http://bokomint.local:8765

  Or via tunnel (no firewall change):
    ./deploy_bokomint.sh tunnel          # leave running
    qsbk install --serve-url http://127.0.0.1:8765

Environment:
  QSBK_REMOTE_HOST   default: bokomint.local
  QSBK_REMOTE_USER   default: \$USER
  QSBK_REMOTE_PATH   default: ~/quorascrapper

Extension (Mac Chrome): http://bokomint.local:8765
  qsbk install --serve-url http://bokomint.local:8765
EOF
}

remote() {
  ssh -o BatchMode=yes -o ServerAliveInterval=30 "$REMOTE" "$@"
}

remote_compose() {
  remote "cd ${REMOTE_PATH} && CI=1 ${REMOTE_COMPOSE} $*"
}

sync_repo() {
  echo "→ Syncing ${ROOT}/ → ${REMOTE}:${REMOTE_PATH}/"
  rsync -avz --delete "${RSYNC_EXCLUDES[@]}" "${ROOT}/" "${REMOTE}:${REMOTE_PATH}/"
}

env_source_file() {
  if [[ -n "${QSBK_ENV_SOURCE:-}" ]]; then
    echo "${QSBK_ENV_SOURCE}"
    return 0
  fi
  local candidate
  for candidate in \
    "${ROOT}/.env.production" \
    "${ROOT}/.env.container" \
    "${HOME}/.config/qsbk/env"; do
    if [[ -f "$candidate" ]] && ! grep -qE 'username:password|secure_password|your-connection' "$candidate"; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

copy_env() {
  local src
  if ! src="$(env_source_file)"; then
    return 1
  fi
  echo "→ Copying $(basename "$src") → ${REMOTE_HOST} (KAFKA_BOOTSTRAP=127.0.0.1:19092)"
  sed 's/^KAFKA_BOOTSTRAP=.*/KAFKA_BOOTSTRAP=127.0.0.1:19092/' "$src" \
    | ssh -o BatchMode=yes "$REMOTE" "cat > ${REMOTE_PATH}/.env.container"
  return 0
}

ensure_remote_env() {
  if remote "test -f ${REMOTE_PATH}/.env.container" \
    && ! remote "grep -qE 'username:password|secure_password|your-connection' ${REMOTE_PATH}/.env.container"; then
    return 0
  fi
  if copy_env; then
    return 0
  fi
  cat >&2 <<EOF
Missing ${REMOTE_PATH}/.env.container on ${REMOTE_HOST}.

Create it locally, then: ./deploy_bokomint.sh env
Or SSH in: cp .env.example .env.container  (KAFKA_BOOTSTRAP=127.0.0.1:19092)
EOF
  exit 1
}

remote_build() {
  echo "→ Building ${IMAGE} on ${REMOTE_HOST} (first run ~5–10 min; logs below)"
  remote "cd ${REMOTE_PATH} && podman build --progress=plain -f Dockerfile -t ${IMAGE} ."
  echo "→ Build finished."
}

start_stack() {
  echo "→ Running preflight..."
  remote_compose run --rm preflight
  echo "→ Starting subscriber + serve..."
  remote_compose up -d "${STACK_SERVICES[@]}"
  echo ""
  echo "qsbk stack on ${REMOTE_HOST}:"
  echo "  serve       http://${REMOTE_HOST}:8765/ping"
  echo "  subscriber  Kafka → MongoDB"
  echo ""
  echo "Mac extension: qsbk install --serve-url http://${REMOTE_HOST}:8765"
}

case "${1:-}" in
  env)
    sync_repo
    copy_env || {
      echo "No ${ROOT}/.env.container to copy" >&2
      exit 1
    }
    ;;
  sync)
    sync_repo
    ;;
  build)
    sync_repo
    ensure_remote_env
    remote_build
    ;;
  preflight)
    sync_repo
    ensure_remote_env
    remote_compose run --rm preflight
    ;;
  up)
    sync_repo
    ensure_remote_env
    remote_build
    start_stack
    ;;
  down)
    remote_compose down
    ;;
  logs)
    shift || true
    case "${1:-}" in
      serve) targets=(qsbk-serve) ;;
      subscriber) targets=(kafka-subscriber) ;;
      "") targets=(kafka-subscriber qsbk-serve) ;;
      *) echo "Unknown service: $1" >&2; exit 1 ;;
    esac
    remote_compose logs -f "${targets[@]}"
    ;;
  status)
    remote_compose ps
    ;;
  rebuild)
    sync_repo
    ensure_remote_env
    remote_build
    remote_compose up -d --force-recreate "${STACK_SERVICES[@]}"
    ;;
  tunnel)
    echo "→ Forwarding http://127.0.0.1:8765 → ${REMOTE_HOST}:8765 (Ctrl+C to stop)"
    echo "  In another terminal: curl http://127.0.0.1:8765/ping"
    echo "  qsbk install --serve-url http://127.0.0.1:8765"
    exec ssh -N -L 8765:127.0.0.1:8765 "$REMOTE"
    ;;
  *)
    usage
    exit 1
    ;;
esac
