#!/bin/bash
set -uo pipefail

# Project directory (can be overridden via --project-dir)
PROJECT_DIR="${GITHUB_WORKSPACE:-$(pwd)}"

# Build directory
BUILD_DIR=""

# Storage directory on /mnt
STORAGE_DIR="/mnt/chromium-build"

# Options
DRY_RUN=false
VERBOSE=false
FORCE=false

log_info() {
    echo "[INFO] $*"
}

log_error() {
    echo "[ERROR] $*" >&2
}

log_warn() {
    echo "[WARN] $*"
}

log_section() {
    echo ""
    echo "$*"
}

log_debug() {
    if [ "$VERBOSE" = true ]; then
        echo "[DEBUG] $*"
    fi
}

log_step() {
    echo "[$1] $2"
}

show_usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Setup storage optimization for Chromium Windows build on Linux.
Symlinks ./build/src to /mnt to avoid running out of disk space.

OPTIONS:
    --project-dir PATH    Project root directory (default: \$GITHUB_WORKSPACE or current dir)
    --build-dir PATH      Build directory (default: \$PROJECT_DIR/build)
    --storage-dir PATH    Storage directory on /mnt (default: /mnt/chromium-build)
    --dry-run            Simulate operations without making changes
    --verbose            Show detailed debug output
    --force              Force overwrite existing symlinks
    -h, --help           Show this help message

EXAMPLES:
    # Basic usage (auto-detect project dir)
    ./setup-chromium-storage.sh

    # Verbose mode with custom paths
    ./setup-chromium-storage.sh --verbose --project-dir /home/runner/work/project

    # Dry run to see what would happen
    ./setup-chromium-storage.sh --dry-run

EOF
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --project-dir)
                PROJECT_DIR="$2"
                shift 2
                ;;
            --build-dir)
                BUILD_DIR="$2"
                shift 2
                ;;
            --storage-dir)
                STORAGE_DIR="$2"
                shift 2
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --verbose)
                VERBOSE=true
                shift
                ;;
            --force)
                FORCE=true
                shift
                ;;
            -h|--help)
                show_usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done

    if [ -z "$BUILD_DIR" ]; then
        BUILD_DIR="${PROJECT_DIR}/build"
    fi
}

human_readable_size() {
    local bytes=$1
    local gb=$((bytes / 1024 / 1024 / 1024))
    local mb=$(( (bytes / 1024 / 1024) % 1024 ))

    if [ "$gb" -gt 0 ]; then
        echo "${gb}.${mb}GB"
    else
        echo "${mb}MB"
    fi
}

execute_command() {
    local description=$1
    shift

    log_debug "Executing: $*"

    if [ "$DRY_RUN" = true ]; then
        log_warn "[DRY RUN] Would execute: $*"
        return 0
    fi

    if "$@"; then
        return 0
    else
        log_error "$description failed"
        return 1
    fi
}

verify_environment() {
    log_step "1/4" "Environment Check"

    # Check if project directory exists
    log_debug "Checking project directory: $PROJECT_DIR"
    if [ ! -d "$PROJECT_DIR" ]; then
        log_error "Project directory does not exist: $PROJECT_DIR"
        log_error "Please specify correct path with --project-dir"
        return 1
    fi
    log_info "Project directory exists: $PROJECT_DIR"

    # Check if /mnt is available
    log_debug "Checking /mnt availability"
    if [ ! -d "/mnt" ]; then
        log_error "/mnt directory does not exist"
        log_error "This script requires /mnt partition for storage optimization"
        return 1
    fi
    log_info "/mnt directory is available"

    # Run permission verification script if available
    local verify_script
    verify_script="$(dirname "$0")/verify-mnt-permissions.sh"

    if [ -f "$verify_script" ]; then
        log_debug "Running permission verification: $verify_script"
        if ! bash "$verify_script"; then
            log_error "/mnt permission verification failed"
            log_error "Please fix the issues reported above"
            return 1
        fi
    else
        log_warn "Permission verification script not found: $verify_script"
        log_warn "Proceeding without full verification"

        if ! touch "${STORAGE_DIR}/.write-test" 2>/dev/null; then
            log_error "Cannot write to ${STORAGE_DIR} - permission denied"
            log_error "Please ensure ${STORAGE_DIR} exists and is writable"
            return 1
        fi
        rm -f "${STORAGE_DIR}/.write-test"
        log_info "${STORAGE_DIR} is writable"
    fi

    # Check build directory status
    log_debug "Checking build directory: $BUILD_DIR"
    if [ ! -d "$BUILD_DIR" ]; then
        log_info "Build directory does not exist yet: $BUILD_DIR"
        log_info "Will create symlink in pre-creation mode"
    else
        log_info "Build directory exists: $BUILD_DIR"
    fi

    return 0
}

setup_symlink() {
    log_step "2/4" "Create Symbolic Link"

    local src_dir="${BUILD_DIR}/src"
    local storage_src_dir="${STORAGE_DIR}/src"

    log_debug "Source directory path: $src_dir"
    log_debug "Storage directory path: $storage_src_dir"

    # Verify storage directory exists (should be created by workflow)
    if [ ! -d "$STORAGE_DIR" ]; then
        log_error "Storage directory does not exist: $STORAGE_DIR"
        log_error ""
        log_error "Expected: /mnt/chromium-build should be created by workflow"
        log_error "Please check workflow preparation step:"
        log_error "  sudo mkdir -p /mnt/chromium-build"
        log_error "  sudo chown \$(whoami):\$(id -gn) /mnt/chromium-build"
        return 1
    fi

    # Verify we have write permission
    if ! touch "${STORAGE_DIR}/.permission-test" 2>/dev/null; then
        log_error "No write permission to storage directory: $STORAGE_DIR"
        log_error ""
        log_error "Directory ownership:"
        ls -ld "$STORAGE_DIR"
        log_error ""
        log_error "Current user: $(whoami) (UID: $(id -u), GID: $(id -g))"
        log_error ""
        log_error "Please verify workflow preparation step set correct ownership"
        return 1
    fi
    rm -f "${STORAGE_DIR}/.permission-test"

    log_info "Storage directory exists with correct permissions: $STORAGE_DIR"

    # Handle existing src directory
    if [ -e "$src_dir" ]; then
        if [ -L "$src_dir" ]; then
            # It's already a symlink
            local link_target
            link_target=$(readlink -f "$src_dir")

            if [ "$link_target" = "$storage_src_dir" ]; then
                log_info "Symlink already exists and points to correct location"
                log_info "Skipping symlink creation"
                return 0
            else
                log_warn "Symlink exists but points to wrong location: $link_target"

                if [ "$FORCE" = true ]; then
                    log_warn "Force mode enabled - removing existing symlink"
                    execute_command "Remove incorrect symlink" rm "$src_dir"
                else
                    log_error "Existing symlink points to unexpected location"
                    log_error "Use --force to overwrite, or manually remove: $src_dir"
                    return 1
                fi
            fi
        elif [ -d "$src_dir" ]; then
            # It's a real directory
            log_warn "Real directory exists: $src_dir"

            # Check if it has data
            local dir_size
            dir_size=$(du -sb "$src_dir" 2>/dev/null | cut -f1 || echo "0")

            log_debug "Directory size: $(human_readable_size "$dir_size")"

            if [ "$dir_size" -lt 1048576 ]; then
                # Less than 1MB - likely empty or minimal
                log_info "Directory is empty or minimal ($(human_readable_size "$dir_size"))"
                log_info "Removing and creating symlink"

                execute_command "Remove empty directory" rm -rf "$src_dir"
            else
                # Has data - need to move
                log_warn "Directory contains data: $(human_readable_size "$dir_size")"
                log_info "Moving data to /mnt storage..."

                if [ -d "$storage_src_dir" ]; then
                    log_error "Storage directory already exists: $storage_src_dir"
                    log_error "Cannot move - destination already exists"
                    log_error "Please manually inspect and resolve"
                    return 1
                fi

                execute_command "Move directory to storage" mv "$src_dir" "$storage_src_dir"
                log_info "Data moved successfully"
            fi
        else
            log_error "Unexpected file type at: $src_dir"
            log_error "Please manually inspect and remove this file"
            return 1
        fi
    else
        log_debug "Source directory does not exist - will create symlink in pre-creation mode"
    fi

    # Create src directory in storage if needed
    if [ ! -d "$storage_src_dir" ]; then
        execute_command "Create storage src directory" mkdir -p "$storage_src_dir"
        log_info "Created storage src directory: $storage_src_dir"
    fi

    # Create build directory if needed
    if [ ! -d "$BUILD_DIR" ]; then
        execute_command "Create build directory" mkdir -p "$BUILD_DIR"
        log_info "Created build directory: $BUILD_DIR"
    fi

    # Create the symlink
    execute_command "Create symbolic link" ln -s "$storage_src_dir" "$src_dir"
    log_info "Symbolic link created: $src_dir -> $storage_src_dir"
    log_info "Mode: Pre-creation (source code will be written directly to /mnt)"

    return 0
}

verify_symlink() {
    log_step "3/4" "Verify Symbolic Link"

    local src_dir="${BUILD_DIR}/src"
    local storage_src_dir="${STORAGE_DIR}/src"

    # Check symlink exists
    if [ ! -L "$src_dir" ]; then
        log_error "Symlink does not exist: $src_dir"
        return 1
    fi
    log_info "Symlink exists"

    # Check symlink target
    local link_target
    link_target=$(readlink -f "$src_dir")

    if [ "$link_target" != "$storage_src_dir" ]; then
        log_error "Symlink points to wrong location"
        log_error "Expected: $storage_src_dir"
        log_error "Actual: $link_target"
        return 1
    fi
    log_info "Symlink points to correct location"

    # Test write through symlink
    local test_file="${src_dir}/.storage-test-$$"
    log_debug "Testing write through symlink: $test_file"

    if [ "$DRY_RUN" = true ]; then
        log_warn "[DRY RUN] Would test write through symlink"
        return 0
    fi

    if echo "storage test" > "$test_file" 2>/dev/null; then
        log_info "Write through symlink successful"

        # Verify file actually exists in /mnt
        local actual_file="${storage_src_dir}/.storage-test-$$"
        if [ -f "$actual_file" ]; then
            log_info "File verified in /mnt storage"

            # Verify content
            if grep -q "storage test" "$actual_file"; then
                log_info "File content verified"

                # Clean up
                rm -f "$test_file"
                log_debug "Test file cleaned up"

                return 0
            else
                log_error "File content verification failed"
                rm -f "$test_file"
                return 1
            fi
        else
            log_error "File not found in /mnt storage"
            rm -f "$test_file"
            return 1
        fi
    else
        log_error "Write through symlink failed"
        return 1
    fi
}

show_space_report() {
    log_step "4/4" "Space Report"

    # Root partition
    local root_info
    root_info=$(df -h / | tail -1)
    local root_avail
    root_avail=$(echo "$root_info" | awk '{print $4}')
    local root_usage
    root_usage=$(echo "$root_info" | awk '{print $5}')

    echo "  Root partition (/):"
    echo "    Available: $root_avail"
    echo "    Usage: $root_usage"

    # /mnt partition
    local mnt_info
    mnt_info=$(df -h /mnt | tail -1)
    local mnt_avail
    mnt_avail=$(echo "$mnt_info" | awk '{print $4}')
    local mnt_usage
    mnt_usage=$(echo "$mnt_info" | awk '{print $5}')

    echo "  /mnt partition:"
    echo "    Available: $mnt_avail"
    echo "    Usage: $mnt_usage"

    # Total available
    local root_avail_kb
    root_avail_kb=$(df -k / | tail -1 | awk '{print $4}')
    local mnt_avail_kb
    mnt_avail_kb=$(df -k /mnt | tail -1 | awk '{print $4}')
    local total_avail_gb=$(( (root_avail_kb + mnt_avail_kb) / 1024 / 1024 ))

    echo "  Total available space: ${total_avail_gb} GB"
    echo ""

    # Estimated usage
    log_info "Estimated usage for Chromium Release build:"
    echo "  Root partition: 40-50 GB (artifacts.zip + system files)"
    echo "  /mnt partition: 40-60 GB (source code + build output)"
    echo ""

    # Warning if space might be tight
    if [ "$total_avail_gb" -lt 100 ]; then
        log_warn "Total available space is less than 100 GB"
        log_warn "Build may fail if space is insufficient"
        log_warn "Monitor disk usage during build process"
    else
        log_info "Sufficient space available for build"
    fi
}

main() {
    # Parse command line arguments
    parse_arguments "$@"

    # Print header
    echo "Chromium Storage Optimization Setup"
    echo "Date: $(date)"
    echo "Host: $(hostname)"
    echo "User: $(whoami)"
    echo ""
    echo "Configuration:"
    echo "  Project directory: $PROJECT_DIR"
    echo "  Build directory: $BUILD_DIR"
    echo "  Storage directory: $STORAGE_DIR"
    echo "  Dry run: $DRY_RUN"
    echo "  Verbose: $VERBOSE"
    echo "  Force: $FORCE"
    echo ""

    # Step 1: Verify environment
    if ! verify_environment; then
        log_error "Environment verification failed"
        return 1
    fi

    # Step 2: Setup symlink
    if ! setup_symlink; then
        log_error "Symlink setup failed"
        return 1
    fi

    # Step 3: Verify symlink
    if ! verify_symlink; then
        log_error "Symlink verification failed"
        return 1
    fi

    # Step 4: Show space report
    show_space_report

    # Success message
    echo ""
    log_info "Storage optimization setup completed successfully"
    echo ""
    log_info "What happens next:"
    echo "  1. Chromium source code will be downloaded to ./build/src"
    echo "  2. Due to symlink, data will actually be written to /mnt"
    echo "  3. This prevents root partition from running out of space"
    echo "  4. Build artifacts will remain on root partition"
    echo ""

    return 0
}

# Run main function
main "$@"