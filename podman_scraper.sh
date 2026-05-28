#!/bin/bash
set -euo pipefail

IMAGE_NAME="quora-scraper"
TAG="latest"
CONTAINER_NAME="quora-scraper"

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log() { echo -e "${BLUE}[INFO]${NC} $*"; }
ok() { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err() { echo -e "${RED}[ERR]${NC} $*"; }

ensure_podman() { command -v podman >/dev/null || { err "Podman not installed"; exit 1; }; }

build() {
  ensure_podman
  log "Building scraper image..."
  podman build -f Dockerfile.scraper -t ${IMAGE_NAME}:${TAG} .
  ok "Built ${IMAGE_NAME}:${TAG}"
}

stop_rm() {
  if podman ps -aq -f name=${CONTAINER_NAME} | grep -q .; then
    log "Stopping/removing existing ${CONTAINER_NAME}..."
    podman rm -f ${CONTAINER_NAME} || true
  fi
}

start() {
  ensure_podman
  if [ ! -f .env.scraper ]; then
    warn ".env.scraper not found; creating a template..."
    cat > .env.scraper <<'EOF'
# Required
PROFILE_URL=https://pt.quora.com/profile/Jo%C3%A3o-Eurico-de-Aguiar-Lima/answers
SENDER=kafka
KAFKA_BOOTSTRAP=bokomint.local:19092
KAFKA_TOPIC=quora-answers

# Optional
LOG_LEVEL=INFO
MAX_RESULTS=200
SCROLL_PAUSE=1.5
EOF
    warn "Edit .env.scraper and re-run start if needed."
  fi
  stop_rm
  log "Starting ${CONTAINER_NAME}..."
  podman run -d --name ${CONTAINER_NAME} \
    --env-file .env.scraper \
    -v "$(pwd)/logs:/logs" \
    -e LOG_FILE_ENABLED=1 -e LOG_FILE_PATH=/logs/scraper.log \
    --restart unless-stopped \
    --network host \
    ${IMAGE_NAME}:${TAG}
  ok "Started ${CONTAINER_NAME}"
}

logs() { ensure_podman; podman logs -f ${CONTAINER_NAME}; }
status() { ensure_podman; podman ps -f name=${CONTAINER_NAME}; }
shell() { ensure_podman; podman exec -it ${CONTAINER_NAME} /bin/bash; }

case "${1:-}" in
  build) build ;;
  start) start ;;
  stop) stop_rm ;;
  restart) build; start ;;
  logs) logs ;;
  status) status ;;
  shell) shell ;;
  *) echo "Usage: $0 {build|start|stop|restart|logs|status|shell}"; exit 1 ;;
esac
