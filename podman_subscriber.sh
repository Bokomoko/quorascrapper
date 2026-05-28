#!/bin/bash
# Podman Container Management Script for Kafka Subscriber

set -e

CONTAINER_NAME="quora-kafka-subscriber"
IMAGE_NAME="quora-subscriber"
TAG="latest"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_podman() {
    if ! command -v podman &> /dev/null; then
        print_error "Podman is not installed. Please install Podman first."
        echo "On macOS: brew install podman"
        echo "On Linux: Follow instructions at https://podman.io/getting-started/installation"
        exit 1
    fi
    print_success "Podman is available"
}

check_env_file() {
    if [ ! -f .env.container ]; then
        print_warning "No .env.container file found. Creating from template..."
        cp .env.example .env.container
        print_warning "Please edit .env.container with your MongoDB Atlas connection string"
        print_warning "Then run this script again."
        exit 1
    fi

    if ! grep -q "^MONGODB_URI=mongodb" .env.container; then
        print_error "MONGODB_URI not properly configured in .env.container"
        print_warning "Please set your MongoDB Atlas connection string in .env.container"
        exit 1
    fi

    print_success "Environment configuration found"
}

build_image() {
    print_status "Building Docker image..."
    podman build -t ${IMAGE_NAME}:${TAG} .
    print_success "Image built successfully: ${IMAGE_NAME}:${TAG}"
}

stop_container() {
    if podman ps -q -f name=${CONTAINER_NAME} | grep -q .; then
        print_status "Stopping existing container..."
        podman stop ${CONTAINER_NAME}
        print_success "Container stopped"
    fi

    if podman ps -aq -f name=${CONTAINER_NAME} | grep -q .; then
        print_status "Removing existing container..."
        podman rm ${CONTAINER_NAME}
        print_success "Container removed"
    fi
}

run_container() {
    print_status "Starting Kafka subscriber container..."

    podman run -d \
        --name ${CONTAINER_NAME} \
        --env-file .env.container \
        -v "$(pwd)/logs:/logs" \
        -e LOG_FILE_ENABLED=1 -e LOG_FILE_PATH=/logs/subscriber.log \
        --restart unless-stopped \
        --network host \
        ${IMAGE_NAME}:${TAG}

    print_success "Container started: ${CONTAINER_NAME}"
    print_status "Container ID: $(podman ps -q -f name=${CONTAINER_NAME})"
}

show_logs() {
    print_status "Showing container logs (Ctrl+C to exit)..."
    podman logs -f ${CONTAINER_NAME}
}

show_status() {
    print_status "Container status:"
    podman ps -f name=${CONTAINER_NAME}

    echo ""
    print_status "Recent logs:"
    podman logs --tail 20 ${CONTAINER_NAME}
}

exec_shell() {
    print_status "Opening shell in container..."
    podman exec -it ${CONTAINER_NAME} /bin/bash
}

case "${1:-}" in
    "build")
        check_podman
        build_image
        ;;
    "start")
        check_podman
        check_env_file
        stop_container
        run_container
        ;;
    "stop")
        check_podman
        stop_container
        ;;
    "restart")
        check_podman
        check_env_file
        stop_container
        run_container
        ;;
    "logs")
        check_podman
        show_logs
        ;;
    "status")
        check_podman
        show_status
        ;;
    "shell")
        check_podman
        exec_shell
        ;;
    "rebuild")
        check_podman
        check_env_file
        print_status "Rebuilding and restarting container..."
        stop_container
        build_image
        run_container
        ;;
    *)
        echo "Kafka Subscriber Container Management"
        echo ""
        echo "Usage: $0 {build|start|stop|restart|logs|status|shell|rebuild}"
        echo ""
        echo "Commands:"
        echo "  build     - Build the container image"
        echo "  start     - Start the subscriber container"
        echo "  stop      - Stop and remove the container"
        echo "  restart   - Restart the container"
        echo "  logs      - Show container logs (follow mode)"
        echo "  status    - Show container status and recent logs"
        echo "  shell     - Open interactive shell in container"
        echo "  rebuild   - Rebuild image and restart container"
        echo ""
        echo "Examples:"
        echo "  $0 build                    # Build the image"
        echo "  $0 start                    # Start the subscriber"
        echo "  $0 logs                     # Watch logs in real-time"
        echo "  $0 status                   # Check if container is running"
        echo ""
        exit 1
        ;;
esac
