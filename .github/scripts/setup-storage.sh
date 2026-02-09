#!/bin/bash
set -euxo pipefail

# Configuration
MERGERFS_MOUNT="/mnt/chromium-build"
BRANCH1_DIR="/home/runner/chromium-root"
SDB1_MOUNT="/mnt/chromium-sdb1"
BRANCH2_DIR="${SDB1_MOUNT}/chromium-root"
USE_MERGERFS=true
CURRENT_USER=$(whoami)
CURRENT_GROUP=$(id -gn)

echo "Build Storage Setup"
echo "User: ${CURRENT_USER}:${CURRENT_GROUP}"
echo "Target mount: ${MERGERFS_MOUNT}"
echo ""

# Setup single-partition mode (fallback)
setup_single_partition() {
  echo "[FALLBACK] Setting up single-partition mode"

  sudo mkdir -p "${MERGERFS_MOUNT}"
  sudo chown "${CURRENT_USER}:${CURRENT_GROUP}" "${MERGERFS_MOUNT}"
  sudo chmod 755 "${MERGERFS_MOUNT}"

  echo "[INFO] Single-partition directory created: ${MERGERFS_MOUNT}"
}


# Step 1: Detect /dev/sdb1
echo "Step 1: Detecting /dev/sdb1"
if [ ! -b /dev/sdb1 ]; then
  echo "[SKIP] /dev/sdb1 does not exist (block device not found)"
  USE_MERGERFS=false
else
  echo "[OK] /dev/sdb1 exists"

  if ! sudo blockdev --getsize64 /dev/sdb1 >/dev/null 2>&1; then
    echo "[WARN] /dev/sdb1 is not readable"
    USE_MERGERFS=false
  else
    SIZE_BYTES=$(sudo blockdev --getsize64 /dev/sdb1)
    SIZE_GB=$((SIZE_BYTES / 1024 / 1024 / 1024))
    echo "[INFO] /dev/sdb1 size: ${SIZE_GB}GB"

    FS_TYPE=$(sudo blkid -o value -s TYPE /dev/sdb1 2>/dev/null || echo "unknown")
    echo "[INFO] /dev/sdb1 filesystem: ${FS_TYPE}"
  fi
fi

echo ""

# Step 2: Install mergerfs (if needed)
if [ "${USE_MERGERFS}" = "true" ]; then
  echo "Step 2: Installing mergerfs"

  if command -v mergerfs >/dev/null 2>&1; then
    echo "[INFO] mergerfs already installed"
    MERGERFS_VERSION=$(mergerfs -V 2>&1 | head -n1 || echo "unknown")
    echo "[INFO] Version: ${MERGERFS_VERSION}"
  else
    echo "[INFO] Installing mergerfs 2.41.1 for Ubuntu 24.04 (Noble)..."

    MERGERFS_VERSION="2.41.1"
    MERGERFS_DEB="mergerfs_${MERGERFS_VERSION}.ubuntu-noble_amd64.deb"
    MERGERFS_URL="https://github.com/trapexit/mergerfs/releases/download/${MERGERFS_VERSION}/${MERGERFS_DEB}"
    MERGERFS_TMP="/tmp/${MERGERFS_DEB}"

    # Download deb package
    echo "[INFO] Downloading from ${MERGERFS_URL}..."
    if wget -q -O "${MERGERFS_TMP}" "${MERGERFS_URL}"; then
      echo "[SUCCESS] Download complete"

      # Install deb package
      echo "[INFO] Installing deb package..."
      if sudo dpkg -i "${MERGERFS_TMP}"; then
        MERGERFS_VERSION=$(mergerfs -V 2>&1 | head -n1 || echo "unknown")
        echo "[SUCCESS] mergerfs installed: ${MERGERFS_VERSION}"

        # Cleanup
        rm -f "${MERGERFS_TMP}"
        echo "[INFO] Cleaned up temporary file"
      else
        echo "[ERROR] mergerfs installation failed"
        rm -f "${MERGERFS_TMP}"
        USE_MERGERFS=false
      fi
    else
      echo "[ERROR] Failed to download mergerfs deb package"
      USE_MERGERFS=false
    fi
  fi

  if [ "${USE_MERGERFS}" = "true" ]; then
    echo "[INFO] Configuring FUSE..."

    if [ ! -f /etc/fuse.conf ]; then
      echo "[WARN] /etc/fuse.conf not found, creating..."
      sudo sh -c 'echo "user_allow_other" > /etc/fuse.conf'
    else
      if ! grep -q "user_allow_other" /etc/fuse.conf; then
        echo "[INFO] Adding user_allow_other to /etc/fuse.conf"
        sudo sh -c 'echo "user_allow_other" >> /etc/fuse.conf'
      else
        echo "[INFO] user_allow_other already configured"
      fi
    fi
  fi

  echo ""
fi


# Step 3: Create branch directories
if [ "${USE_MERGERFS}" = "true" ]; then
  echo "Step 3: Creating branch directories"

  echo "[INFO] Creating branch 1: ${BRANCH1_DIR}"
  sudo mkdir -p "${BRANCH1_DIR}"
  sudo chown "${CURRENT_USER}:${CURRENT_GROUP}" "${BRANCH1_DIR}"
  sudo chmod 755 "${BRANCH1_DIR}"
  echo "[SUCCESS] Branch 1 created"

  echo "[INFO] Creating sdb1 mount point: ${SDB1_MOUNT}"
  sudo mkdir -p "${SDB1_MOUNT}"

  echo "[INFO] Mounting /dev/sdb1 to ${SDB1_MOUNT}"

  if mountpoint -q "${SDB1_MOUNT}" 2>/dev/null; then
    echo "[WARN] ${SDB1_MOUNT} already mounted, unmounting..."
    sudo umount "${SDB1_MOUNT}" || true
    sleep 1
  fi

  if sudo mount /dev/sdb1 "${SDB1_MOUNT}"; then
    echo "[SUCCESS] /dev/sdb1 mounted"

    AVAILABLE_MB=$(df -BM "${SDB1_MOUNT}" | awk 'NR==2 {print $4}' | sed 's/M//')
    AVAILABLE_GB=$((AVAILABLE_MB / 1024))
    echo "[INFO] Available space on /dev/sdb1: ${AVAILABLE_GB}GB"

    if [ "${AVAILABLE_MB}" -lt 10240 ]; then
      echo "[WARN] Insufficient space on /dev/sdb1 (${AVAILABLE_GB}GB)"
      sudo umount "${SDB1_MOUNT}" || true
      USE_MERGERFS=false
    else
      echo "[INFO] Creating branch 2: ${BRANCH2_DIR}"
      sudo mkdir -p "${BRANCH2_DIR}"
      sudo chown "${CURRENT_USER}:${CURRENT_GROUP}" "${BRANCH2_DIR}"
      sudo chmod 755 "${BRANCH2_DIR}"
      echo "[SUCCESS] Branch 2 created"
    fi
  else
    echo "[ERROR] Failed to mount /dev/sdb1"
    USE_MERGERFS=false
  fi

  echo ""
fi

# Step 4: Mount mergerfs or setup single-partition
if [ "${USE_MERGERFS}" = "true" ]; then
  echo "Step 4: Mounting mergerfs"

  sudo mkdir -p "${MERGERFS_MOUNT}"

  # Detect kernel version for passthrough.io support
  KERNEL_VERSION=$(uname -r | cut -d. -f1-2)
  KERNEL_MAJOR=$(echo "${KERNEL_VERSION}" | cut -d. -f1)
  KERNEL_MINOR=$(echo "${KERNEL_VERSION}" | cut -d. -f2)

  USE_PASSTHROUGH=false
  if [ "${KERNEL_MAJOR}" -gt 6 ] || ([ "${KERNEL_MAJOR}" -eq 6 ] && [ "${KERNEL_MINOR}" -ge 9 ]); then
    USE_PASSTHROUGH=true
    echo "[INFO] Kernel ${KERNEL_VERSION} supports passthrough.io"
  else
    echo "[INFO] Kernel ${KERNEL_VERSION} does not support passthrough.io (requires 6.9+)"
  fi

  # Build mergerfs options
  MERGERFS_OPTS="allow_other,use_ino,dropcacheonclose=true"
  MERGERFS_OPTS="${MERGERFS_OPTS},category.create=epmfs"
  MERGERFS_OPTS="${MERGERFS_OPTS},category.search=ff"
  MERGERFS_OPTS="${MERGERFS_OPTS},func.getattr=newest"

  # Add passthrough.io if supported (requires cache.files=auto-full)
  if [ "${USE_PASSTHROUGH}" = "true" ]; then
    MERGERFS_OPTS="${MERGERFS_OPTS},cache.files=auto-full"
    MERGERFS_OPTS="${MERGERFS_OPTS},passthrough.io=rw"
    echo "[INFO] Enabling passthrough.io for near-native I/O performance"
  else
    # Fallback to partial caching
    MERGERFS_OPTS="${MERGERFS_OPTS},cache.files=partial"
    echo "[INFO] Using cache.files=partial (passthrough.io unavailable)"
  fi

  echo "[INFO] Mounting: ${BRANCH1_DIR}:${BRANCH2_DIR} → ${MERGERFS_MOUNT}"
  echo "[INFO] Policy: category.create=epmfs (existing path or most free space)"
  echo "[INFO] Options: ${MERGERFS_OPTS}"

  if sudo mergerfs -o "${MERGERFS_OPTS}" \
    "${BRANCH1_DIR}:${BRANCH2_DIR}" \
    "${MERGERFS_MOUNT}"; then

    echo "[SUCCESS] mergerfs mounted successfully"

    sudo chown "${CURRENT_USER}:${CURRENT_GROUP}" "${MERGERFS_MOUNT}"
    sudo chmod 755 "${MERGERFS_MOUNT}"
  else
    echo "[ERROR] mergerfs mount failed"
    USE_MERGERFS=false

    if mountpoint -q "${SDB1_MOUNT}" 2>/dev/null; then
      sudo umount "${SDB1_MOUNT}" || true
    fi

    setup_single_partition
  fi

  echo ""
else
  echo "Step 4: Setting up single-partition mode"
  setup_single_partition
  echo ""
fi

# Step 5: Verification
echo "Step 5: Verification"
if [ ! -d "${MERGERFS_MOUNT}" ]; then
  echo "[FAIL] ${MERGERFS_MOUNT} does not exist"
  exit 1
fi

echo ""
echo "Filesystem Information:"
df -h "${MERGERFS_MOUNT}"
echo ""

if [ "${USE_MERGERFS}" = "true" ]; then
  echo "Branch Information:"
  df -h "${BRANCH1_DIR}" "${BRANCH2_DIR}"
  echo ""
fi

echo "Write Permission Test:"
TEST_FILE="${MERGERFS_MOUNT}/.write-test-$$"
if touch "${TEST_FILE}" 2>/dev/null; then
  echo "[PASS] Write test successful"
  rm -f "${TEST_FILE}"
else
  echo "[FAIL] Write test failed - permission denied"
  ls -ld "${MERGERFS_MOUNT}"
  exit 1
fi

if [ "${USE_MERGERFS}" = "true" ]; then
  echo ""
  echo "File Distribution Test:"
  TEST_FILE2="${MERGERFS_MOUNT}/.distribution-test-$$"
  echo "test" > "${TEST_FILE2}"

  if [ -f "${BRANCH1_DIR}/.distribution-test-$$" ]; then
    echo "[INFO] Test file created on branch 1 (/dev/root)"
  elif [ -f "${BRANCH2_DIR}/.distribution-test-$$" ]; then
    echo "[INFO] Test file created on branch 2 (/dev/sdb1)"
  else
    echo "[WARN] Could not determine file distribution"
  fi

  rm -f "${TEST_FILE2}"
fi

echo ""
echo "Storage Setup Complete"
echo "Mode: $([ "${USE_MERGERFS}" = "true" ] && echo "mergerfs (distributed)" || echo "single-partition")"
echo "Mount Point: ${MERGERFS_MOUNT}"
echo ""
