#!/bin/bash
set -uo pipefail

readonly TEST_DIR="/mnt/chromium-build/chromium-test-$$"
readonly TEST_FILE="${TEST_DIR}/test-file.dat"
readonly LARGE_TEST_SIZE_GB=0.1

# Counters
TESTS_PASSED=0
TESTS_FAILED=0

log_info() {
    echo "[PASS] $*"
}

log_error() {
    echo "[FAIL] $*" >&2
}

log_warn() {
    echo "[WARN] $*"
}

log_section() {
    echo ""
    echo "Testing: $*"
}

test_directory_exists() {
    log_section "/mnt directory accessibility"

    if [ ! -d "/mnt" ]; then
        log_error "/mnt directory does not exist"
        return 1
    fi

    if [ ! -r "/mnt" ]; then
        log_error "/mnt directory is not readable"
        return 1
    fi

    log_info "/mnt directory exists and is accessible"
    return 0
}

test_directory_creation() {
    log_section "Directory creation permissions"

    # Note: /mnt/chromium-build should already be created by workflow with proper ownership
    # This test creates a subdirectory to verify permissions
    if mkdir -p "$TEST_DIR" 2>/dev/null; then
        log_info "Directory creation successful: $TEST_DIR"
        return 0
    else
        log_error "Failed to create directory: $TEST_DIR"
        log_error "Permission denied - /mnt/chromium-build may not be writable by current user"
        log_error ""
        log_error "Expected: /mnt/chromium-build should be owned by current user"
        log_error "Current user: $(whoami) (UID: $(id -u), GID: $(id -g))"
        log_error ""
        log_error "Please check workflow preparation step:"
        log_error "  sudo mkdir -p /mnt/chromium-build"
        log_error "  sudo chown \$(whoami):\$(id -gn) /mnt/chromium-build"
        return 1
    fi
}

test_file_write() {
    log_section "File write permissions"

    if echo "test content" > "$TEST_FILE" 2>/dev/null; then
        log_info "File write successful"

        # Verify content
        if grep -q "test content" "$TEST_FILE"; then
            log_info "File content verified"
            return 0
        else
            log_error "File content verification failed"
            return 1
        fi
    else
        log_error "Failed to write file: $TEST_FILE"
        return 1
    fi
}

test_large_file_write() {
    log_section "Large file write (${LARGE_TEST_SIZE_GB}GB)"

    local start_time
    start_time=$(date +%s)

    log_info "Creating ${LARGE_TEST_SIZE_GB}GB test file (may take 10-30 seconds)..."

    # Use timeout to prevent hanging
    if timeout 30 dd if=/dev/zero of="${TEST_DIR}/large-test.dat" bs=1M count=$((LARGE_TEST_SIZE_GB * 1024)) \
       conv=fdatasync 2>/dev/null; then

        local end_time
        end_time=$(date +%s)
        local duration=$((end_time - start_time))

        local file_size
        file_size=$(du -h "${TEST_DIR}/large-test.dat" | cut -f1)

        log_info "Large file write successful: ${file_size} in ${duration}s"

        # Clean up immediately to free space
        rm -f "${TEST_DIR}/large-test.dat"

        return 0
    else
        log_error "Failed to write ${LARGE_TEST_SIZE_GB}GB file (timeout or I/O error)"
        log_error "Possible causes: insufficient space, quota limit, or slow disk"
        # Clean up partial file
        rm -f "${TEST_DIR}/large-test.dat" 2>/dev/null
        return 1
    fi
}

test_symlink_creation() {
    log_section "Symbolic link creation"

    local link_target="${TEST_DIR}/link-target"
    local link_name="${TEST_DIR}/test-symlink"

    # Create target file
    if ! echo "link target" > "$link_target"; then
        log_error "Failed to create symlink target file"
        return 1
    fi

    # Create symbolic link
    if ln -s "$link_target" "$link_name" 2>/dev/null; then
        log_info "Symbolic link creation successful"

        # Verify link
        if [ -L "$link_name" ] && [ -e "$link_name" ]; then
            log_info "Symbolic link verified"

            # Test read through link
            if grep -q "link target" "$link_name"; then
                log_info "Read through symbolic link successful"
                return 0
            else
                log_error "Failed to read through symbolic link"
                return 1
            fi
        else
            log_error "Symbolic link verification failed"
            return 1
        fi
    else
        log_error "Failed to create symbolic link"
        log_error "Filesystem may not support symlinks"
        return 1
    fi
}

test_executable_permissions() {
    log_section "Executable file permissions"

    local exec_file="${TEST_DIR}/test-executable.sh"

    # Create executable script
    cat > "$exec_file" <<'EOF'
#!/bin/bash
echo "executable test"
EOF

    # Set executable permission
    if chmod +x "$exec_file" 2>/dev/null; then
        log_info "Executable permission set successfully"

        # Test execution
        if "$exec_file" 2>/dev/null | grep -q "executable test"; then
            log_info "Executable file execution successful"
            return 0
        else
            log_error "Failed to execute file (noexec mount option?)"
            return 1
        fi
    else
        log_error "Failed to set executable permission"
        return 1
    fi
}

test_available_space() {
    log_section "Available disk space"

    local available_kb
    available_kb=$(df -k /mnt | tail -1 | awk '{print $4}')
    local available_gb=$((available_kb / 1024 / 1024))

    log_info "Available space: ${available_gb} GB"

    # Require at least 60GB for Chromium build
    local required_gb=60

    if [ "$available_gb" -ge "$required_gb" ]; then
        log_info "Sufficient space available (>= ${required_gb}GB required)"
        return 0
    else
        log_error "Insufficient space: ${available_gb}GB available, ${required_gb}GB required"
        return 1
    fi
}

test_inode_availability() {
    log_section "Inode availability"

    local inode_info
    inode_info=$(df -i /mnt | tail -1)
    local available_inodes
    available_inodes=$(echo "$inode_info" | awk '{print $4}')

    log_info "Available inodes: ${available_inodes}"

    # Require at least 1M inodes for Chromium build (many small files)
    local required_inodes=1000000

    if [ "$available_inodes" -ge "$required_inodes" ]; then
        log_info "Sufficient inodes available (>= ${required_inodes} required)"
        return 0
    else
        log_error "Insufficient inodes: ${available_inodes} available, ${required_inodes} required"
        return 1
    fi
}

test_filesystem_type() {
    log_section "Filesystem type"

    local fs_type
    fs_type=$(df -T /mnt | tail -1 | awk '{print $2}')

    log_info "Filesystem type: $fs_type"

    # Preferred filesystems for build performance
    case "$fs_type" in
        ext4|xfs|btrfs)
            log_info "Filesystem type is suitable for build workloads"
            return 0
            ;;
        ext3|ext2)
            log_warn "Filesystem type is acceptable but not optimal"
            log_warn "Consider using ext4, xfs, or btrfs for better performance"
            return 0
            ;;
        tmpfs|ramfs)
            log_warn "Filesystem is memory-backed, may have space limitations"
            return 0
            ;;
        *)
            log_warn "Unknown filesystem type: $fs_type"
            log_warn "Proceeding but performance may vary"
            return 0
            ;;
    esac
}

test_concurrent_write() {
    log_section "Concurrent write operations"

    log_info "Simulating parallel build scenario (4 concurrent writes)..."

    local pids=()
    local test_passed=0

    # Create 4 files concurrently (simulating parallel build)
    for i in {1..4}; do
        dd if=/dev/zero of="${TEST_DIR}/concurrent-${i}.dat" bs=1M count=100 \
           conv=fdatasync 2>/dev/null &
        pids+=($!)
    done

    # Wait for all background jobs
    local all_success=1
    for pid in "${pids[@]}"; do
        if ! wait "$pid"; then
            all_success=0
        fi
    done

    if [ "$all_success" -eq 1 ]; then
        log_info "Concurrent write test successful"
        test_passed=1
    else
        log_error "Concurrent write test failed"
        test_passed=0

        for pid in "${pids[@]}"; do
            kill "$pid" 2>/dev/null || true
        done
    fi

    # Wait a moment to ensure file writes are complete
    sleep 1

    # Clean up
    rm -f "${TEST_DIR}/concurrent-"*.dat 2>/dev/null || true

    return $((1 - test_passed))
}

cleanup() {
    set +e

    if [ -d "$TEST_DIR" ]; then
        echo ""
        echo "Cleaning up test directory"
        rm -rf "$TEST_DIR" 2>/dev/null
        if [ $? -eq 0 ]; then
            log_info "Test directory removed"
        else
            log_warn "Could not remove test directory (non-critical)"
        fi
    fi
}

main() {
    echo "/mnt Permission Verification Report"
    echo "Date: $(date)"
    echo "Host: $(hostname)"
    echo "User: $(whoami)"
    echo ""

    # Array of test functions
    local tests=(
        "test_directory_exists"
        "test_directory_creation"
        "test_file_write"
        "test_large_file_write"
        "test_symlink_creation"
        "test_executable_permissions"
        "test_available_space"
        "test_inode_availability"
        "test_filesystem_type"
        "test_concurrent_write"
    )

    set +e

    # Run all tests
    for test_func in "${tests[@]}"; do
        if $test_func; then
            ((TESTS_PASSED++))
        else
            ((TESTS_FAILED++))
        fi
    done

    # Re-enable set -e
    set -e

    # Summary
    echo ""
    echo "Test Summary"
    echo "Total tests: $((TESTS_PASSED + TESTS_FAILED))"
    echo "Passed: ${TESTS_PASSED}"
    echo "Failed: ${TESTS_FAILED}"

    # Disk usage summary
    echo ""
    echo "Disk Usage Summary"
    df -h /mnt | tail -1 | awk '{printf "Total: %s, Used: %s, Available: %s, Usage: %s\n", $2, $3, $4, $5}'

    # Final result
    echo ""
    if [ "$TESTS_FAILED" -eq 0 ]; then
        log_info "All checks passed"
        log_info "/mnt is ready for Chromium build"
        return 0
    else
        log_error "Some checks failed"
        log_error "/mnt may not be suitable for Chromium build"
        log_error "Please review the errors above and fix the issues"
        return 1
    fi
}

# Trap cleanup on exit
trap cleanup EXIT

# Run main function
main "$@"