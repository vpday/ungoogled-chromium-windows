#!/bin/bash
set -euo pipefail

# Storage directory on /mnt
STORAGE_DIR="/mnt/chromium-build"

log_info() {
    echo -e "[PASS] $*"
}

log_error() {
    echo -e "[FAIL] $*" >&2
}

main() {
    echo "Preparing /mnt storage directory"
    echo ""

    # Dynamically get current user and group (supports self-hosted runners)
    CURRENT_USER=$(whoami)
    CURRENT_GROUP=$(id -gn)

    # Create storage directory with sudo
    echo "Creating directory: ${STORAGE_DIR}"
    sudo mkdir -p "${STORAGE_DIR}"

    # Change ownership to current user
    echo "Setting ownership to ${CURRENT_USER}:${CURRENT_GROUP}"
    sudo chown "${CURRENT_USER}:${CURRENT_GROUP}" "${STORAGE_DIR}"

    # Set permissions (755)
    echo "Setting permissions (755)"
    sudo chmod 755 "${STORAGE_DIR}"

    # Verify
    echo ""
    echo "Directory created successfully:"
    ls -ld "${STORAGE_DIR}"

    # Test write permissions
    echo ""
    echo "Testing write permissions..."
    if touch "${STORAGE_DIR}/.write-test" 2>/dev/null; then
        log_info "Write test successful"
        rm "${STORAGE_DIR}/.write-test"
    else
        log_error "Write test failed"
        return 1
    fi

    echo ""
    echo "/mnt storage directory is ready"

    return 0
}

# Run main function
main "$@"
