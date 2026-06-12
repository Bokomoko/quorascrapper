#!/bin/bash
# Alias for the qsbk serve + subscriber stack.
exec "$(dirname "$0")/podman_subscriber.sh" "$@"
