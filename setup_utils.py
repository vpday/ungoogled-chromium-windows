#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 The ungoogled-chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
Setup utilities for ungoogled-chromium Windows build.

This module provides toolchain and environment setup utilities including:
- Google Storage file downloads
- Domain substitution for tool downloading
- Sysroot installation
- Clang/Rust toolchain setup
- Windows toolchain configuration
"""

import hashlib
import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parent / "ungoogled-chromium" / "utils")
)
from _common import ENCODING, get_logger

sys.path.pop(0)

from build_common import run_build_process, get_host_arch, get_target_arch_from_args

_ROOT_DIR = Path(__file__).resolve().parent


def download_from_sha1(sha1_file: Path, output_file: Path, bucket: str):
    """
    Download file from Google Storage

    Args:
        sha1_file: Path to the .sha1 file
        output_file: Path to the output file
        bucket: Google Storage bucket path
    """
    # Read SHA1 value
    if not sha1_file.exists():
        get_logger().error(f"SHA1 file does not exist: {sha1_file}")
        sys.exit(1)

    expected_sha1 = sha1_file.read_text().strip()
    get_logger().info(f"SHA1 value: {expected_sha1}")

    # Build URL
    url = f"https://storage.googleapis.com/{bucket}/{expected_sha1}"
    get_logger().info(f"Download URL: {url}")

    # Download file
    get_logger().info("Starting download...")
    try:
        urllib.request.urlretrieve(url, output_file)
    except Exception as e:
        get_logger().error(f"Error: Download failed - {e}")
        sys.exit(1)

    # Verify SHA1
    get_logger().info("Verifying file integrity...")
    sha1 = hashlib.sha1()
    with open(output_file, "rb") as f:
        while chunk := f.read(8192):
            sha1.update(chunk)

    actual_sha1 = sha1.hexdigest()
    if actual_sha1 != expected_sha1:
        get_logger().error(
            f"SHA1 verification failed! Expected: {expected_sha1}, Actual: {actual_sha1}"
        )
        output_file.unlink()
        sys.exit(1)

    # Set executable permission
    output_file.chmod(0o755)
    get_logger().info(f"Download complete: {output_file}")


def download_v8_builtins_pgo_profiles(source_tree, disable_ssl_verification=False):
    """
    Download V8 Builtins PGO profiles from Google Cloud Storage.

    This function automatically fetches the list of available profile files for the
    current V8 version and downloads them. If the API query fails, it falls back to
    a known list of profile files.

    Args:
        source_tree: Path to the Chromium source tree (build/src)
        disable_ssl_verification: Whether to disable SSL verification for downloads
    """

    # Parse V8 version from v8-version.h
    version_file = source_tree / "v8" / "include" / "v8-version.h"
    if not version_file.exists():
        get_logger().warning(f"V8 version file not found: {version_file}")
        return

    version_content = version_file.read_text(encoding="utf-8")
    version_pattern = r"#define V8_MAJOR_VERSION (\d+)\s+#define V8_MINOR_VERSION (\d+)\s+#define V8_BUILD_NUMBER (\d+)\s+#define V8_PATCH_LEVEL (\d+)"
    match = re.search(version_pattern, version_content, re.MULTILINE | re.DOTALL)

    if not match:
        get_logger().warning("Could not parse V8 version from v8-version.h")
        return

    major, minor, build, patch = match.groups()
    v8_version = f"{major}.{minor}.{build}.{patch}"
    get_logger().info(f"V8 version: {v8_version}")

    # Check if build and patch are both 0 (no profiles exist)
    if build == "0" and patch == "0":
        get_logger().info("V8 version has no PGO profiles (development version)")
        return

    # Profile files directory
    profiles_dir = source_tree / "v8" / "tools" / "builtins-pgo" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    bucket = "chromium-v8-builtins-pgo"
    version_prefix = f"by-version/{v8_version}/"

    # Configure SSL context if needed
    if disable_ssl_verification:
        import ssl

        ssl_context = ssl._create_unverified_context()
    else:
        ssl_context = None

    # Fetch list of available profile files from GCS JSON API
    api_url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o?prefix={version_prefix}"
    get_logger().info(f"Fetching file list from GCS: {api_url}")

    try:
        if ssl_context:
            response = urllib.request.urlopen(api_url, context=ssl_context)
        else:
            response = urllib.request.urlopen(api_url)

        data = json.loads(response.read().decode("utf-8"))

        if "items" not in data or not data["items"]:
            get_logger().warning(f"No PGO profiles found for V8 version {v8_version}")
            return

        # Extract file names from the response
        profile_files = []
        for item in data["items"]:
            # Remove the version prefix to get just the filename
            filename = item["name"].replace(version_prefix, "")
            if filename:  # Skip empty names (directory itself)
                profile_files.append(filename)

        get_logger().info(
            f"Found {len(profile_files)} profile files: {', '.join(profile_files)}"
        )

    except Exception as e:
        get_logger().warning(f"Failed to fetch file list from GCS: {e}")
        get_logger().info("Falling back to known profile file list")
        # Fallback to known files if API query fails
        profile_files = [
            "x64.profile",
            "x64-rl.profile",
            "x86.profile",
            "x86-rl.profile",
            "meta.json",
        ]

    # Download each profile file
    base_url = f"https://storage.googleapis.com/{bucket}/{version_prefix}"
    downloaded_count = 0

    for profile_file in profile_files:
        output_path = profiles_dir / profile_file

        # Skip if already exists
        if output_path.exists():
            get_logger().info(f"Profile already exists: {profile_file}")
            downloaded_count += 1
            continue

        url = f"{base_url}{profile_file}"
        get_logger().info(f"Downloading {profile_file}")

        try:
            if ssl_context:
                urllib.request.urlretrieve(url, output_path)
            else:
                urllib.request.urlretrieve(url, output_path)
            get_logger().info(f"Downloaded: {profile_file}")
            downloaded_count += 1
        except Exception as e:
            get_logger().warning(f"Failed to download {profile_file}: {e}")
            # Clean up partial download
            if output_path.exists():
                output_path.unlink()

    if downloaded_count == len(profile_files):
        get_logger().info("All V8 Builtins PGO profiles downloaded successfully")
    elif downloaded_count > 0:
        get_logger().info(
            f"Downloaded {downloaded_count}/{len(profile_files)} V8 Builtins PGO profiles"
        )
    else:
        get_logger().warning("No V8 Builtins PGO profiles were downloaded")


def fix_tool_downloading(source_tree):
    """
    Fixes downloading of prebuilt tools and sysroot files by replacing obfuscated domains.
    """
    replacements = [
        # commondatastorage replacement
        (
            r"commondatastorage\.9oo91eapis\.qjz9zk",
            "commondatastorage.googleapis.com",
            [
                "build/linux/sysroot_scripts/sysroots.json",
                "tools/clang/scripts/update.py",
                "tools/clang/scripts/build.py",
            ],
        ),
        # chromium.googlesource replacement
        (
            r"chromium\.9oo91esource\.qjz9zk",
            "chromium.googlesource.com",
            [
                "tools/clang/scripts/build.py",
                "tools/rust/build_rust.py",
                "tools/rust/build_bindgen.py",
            ],
        ),
        # chrome-infra-packages replacement
        (
            r"chrome-infra-packages\.8pp2p8t\.qjz9zk",
            "chrome-infra-packages.appspot.com",
            [
                "tools/rust/build_rust.py",
            ],
        ),
    ]

    # Build an inverted index: file_path -> list of (pattern, replacement)
    file_ops = defaultdict(list)
    for pattern, replacement, file_paths in replacements:
        for rel_path in file_paths:
            # Convert string paths to Path objects relative to source_tree
            file_ops[source_tree / rel_path].append((pattern, replacement))

    # Process each file exactly once
    for file_path, rules in file_ops.items():
        if not file_path.exists():
            get_logger().warning("File not found for patching: %s", file_path)
            continue

        try:
            content = file_path.read_text(encoding=ENCODING)
            new_content = content

            # Apply all registered rules for this file
            for pattern, repl in rules:
                new_content = re.sub(pattern, repl, new_content)

            # Write back only if changes occurred
            if new_content != content:
                file_path.write_text(new_content, encoding=ENCODING)

        except Exception as e:
            get_logger().error("Failed to patch %s: %s", file_path, e)
            raise


def setup_sysroot(source_tree, ci_mode=False):
    """
    Install Linux sysroot for cross-compilation.

    This function installs the necessary Linux sysroot packages required
    for building Windows Chromium from a Linux system.

    Args:
        source_tree: Path object of the source directory
        ci_mode: Boolean indicating if running in CI mode (enables stamp-based skipping)
    """
    # CI mode optimization: skip if already installed
    stamp_file = source_tree / ".sysroot_installed.stamp"

    if ci_mode and stamp_file.exists():
        get_logger().info("Sysroot already installed (stamp file exists), skipping")
        return

    host_arch = get_host_arch()
    target_arch = get_target_arch_from_args()

    # Architecture name mapping for sysroot script
    arch_mapping = {"x64": "amd64", "x86": "i386", "arm64": "arm64"}

    get_logger().info(
        "Installing sysroot for host architecture: %s, target architecture: %s",
        host_arch,
        target_arch,
    )

    # Install host architecture sysroot
    host_sysroot_arch = arch_mapping.get(host_arch, host_arch)
    get_logger().info("Installing host sysroot: %s", host_sysroot_arch)
    run_build_process(
        sys.executable,
        str(source_tree / "build" / "linux" / "sysroot_scripts" / "install-sysroot.py"),
        f"--arch={host_sysroot_arch}",
    )

    # Create stamp file to mark successful installation
    stamp_file.touch()
    get_logger().info("Sysroot installation completed successfully")


def setup_toolchain(source_tree, ci_mode=False):
    """
    Sets up the toolchain components required for cross-compiling Windows Chromium.

    Args:
        source_tree: Path object of the source directory
        ci_mode: Boolean indicating if running in CI mode (passed to setup_sysroot for stamp-based skipping)

    Note:
        This function does not implement its own stamp checking.
        Stamp checking is handled by the caller (build.py) using .setup_toolchain.stamp
    """
    get_logger().info("Setting up toolchain")

    get_logger().info("Building bindgen tool...")
    run_build_process(
        sys.executable,
        str(source_tree / "tools" / "rust" / "build_bindgen.py"),
        "--skip-test",
    )

    # Install Linux sysroot packages for cross-compilation
    # ci_mode is passed through to enable stamp-based skipping in setup_sysroot
    get_logger().info("Installing sysroot packages...")
    setup_sysroot(source_tree, ci_mode)

    get_logger().info("Toolchain setup completed successfully")
