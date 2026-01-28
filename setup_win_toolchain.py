#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 The ungoogled-chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
Windows toolchain downloader for cross-compilation builds

Downloads Windows toolchain files from configured sources,
validates checksums, and merges them into a zip file.
Uses JSON-based configuration with variable substitution support.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, TypedDict

from build_common import (
    run_build_process,
    should_skip_step,
    mark_step_complete,
    get_target_arch_from_args,
)
from setup_utils import download_from_sha1

sys.path.insert(
    0, str(Path(__file__).resolve().parent / "ungoogled-chromium" / "utils")
)
from _common import ENCODING, get_logger

sys.path.pop(0)

# Constants
_ROOT_DIR = Path(__file__).resolve().parent


# Type definitions for toolchain configuration
class ToolchainFile(TypedDict):
    """Single file entry in toolchain configuration"""

    url: str
    filename: str
    sha256: str
    sequence: int


def _substitute_variables(template: str, variables: Dict[str, str]) -> str:
    """
    Substitute {variable_name} patterns in template string.

    Args:
        template: String containing {var} patterns
        variables: Dictionary of variable_name -> value

    Returns:
        String with all variables substituted

    Raises:
        RuntimeError: If variable not found in dict
    """
    try:
        return template.format(**variables)
    except KeyError as e:
        missing_var = str(e).strip("'")
        raise RuntimeError(
            f"Variable substitution failed: '{missing_var}' not defined in variables section. "
            f"Available variables: {', '.join(sorted(variables.keys()))}"
        )


def _validate_toolchain_config(config_data: dict, section: str) -> None:
    """
    Validate toolchain configuration structure.

    Args:
        config_data: Parsed JSON configuration
        section: Section name to validate

    Raises:
        RuntimeError: If validation fails
    """
    # Check section exists
    if section not in config_data:
        available = [
            k for k in config_data.keys() if k not in ("_comment", "variables")
        ]
        raise RuntimeError(
            f"Invalid config: [{section}] section missing in win_toolchain.json. "
            f"Available sections: {', '.join(available)}"
        )

    section_data = config_data[section]

    # Check required keys in section
    required_keys = ["zip_filename", "sha512", "files"]
    for key in required_keys:
        if key not in section_data:
            raise RuntimeError(
                f"Invalid config: '{key}' missing in [{section}] section"
            )

    # Validate files list
    files = section_data["files"]
    if not isinstance(files, list) or len(files) == 0:
        raise RuntimeError(
            f"Invalid config: 'files' in [{section}] must be a non-empty list"
        )

    # Validate each file entry
    required_file_keys = ["url", "filename", "sha256", "sequence"]
    for i, file_entry in enumerate(files):
        for key in required_file_keys:
            if key not in file_entry:
                raise RuntimeError(
                    f"Invalid config: 'files[{i}].{key}' missing in [{section}] section"
                )

    # Validate sequence numbers (should be consecutive starting from 1)
    sequences = [f["sequence"] for f in files]
    expected = list(range(1, len(files) + 1))
    if sorted(sequences) != expected:
        get_logger().warning(
            "Sequence numbers in [%s] are not consecutive (1, 2, 3, ...). "
            "Found: %s. Files will be sorted by sequence number.",
            section,
            sorted(sequences),
        )


def _compute_hash(file_path, algorithm="sha256"):
    """
    Compute hash checksum of a file

    Args:
        file_path: Path to the file
        algorithm: Hash algorithm name ('sha256', 'sha512', etc.)

    Returns:
        str: Hexadecimal hash checksum
    """
    hasher = hashlib.new(algorithm)
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def _compute_sha256(file_path):
    """
    Compute SHA256 checksum of a file

    Args:
        file_path: Path to the file

    Returns:
        str: Hexadecimal SHA256 checksum
    """
    return _compute_hash(file_path, "sha256")


def _compute_sha512(file_path):
    """
    Compute SHA512 checksum of a file

    Args:
        file_path: Path to the file

    Returns:
        str: Hexadecimal SHA512 checksum
    """
    return _compute_hash(file_path, "sha512")


def _validate_zip_file(zip_path, expected_sha512):
    """
    Validate zip file checksum

    Args:
        zip_path: Path to the zip file
        expected_sha512: Expected SHA512 checksum (hex string)

    Returns:
        bool: True if valid, False if invalid or file missing
    """
    if not zip_path.exists():
        get_logger().info("Zip file does not exist: %s", zip_path)
        return False

    get_logger().info("Validating zip file checksum: %s", zip_path.name)
    actual_sha512 = _compute_sha512(zip_path)

    if actual_sha512.lower() == expected_sha512.lower():
        get_logger().info("Zip file validation passed")
        return True
    else:
        get_logger().warning(
            "Zip file checksum mismatch. Expected: %s, Got: %s",
            expected_sha512,
            actual_sha512,
        )
        return False


def _download_with_retry(url, output_path, max_retries=3):
    """
    Download file with retry mechanism

    Args:
        url: Download URL
        output_path: Destination file path
        max_retries: Maximum number of retry attempts (default: 3)

    Raises:
        RuntimeError: If all retry attempts fail
    """
    for attempt in range(max_retries):
        try:
            get_logger().info(
                "Downloading (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                output_path.name,
            )
            urllib.request.urlretrieve(url, str(output_path))
            get_logger().info("Download complete: %s", output_path.name)
            return
        except Exception as e:
            get_logger().warning(
                "Download failed (attempt %d/%d): %s", attempt + 1, max_retries, e
            )
            if attempt < max_retries - 1:
                sleep_time = 2**attempt  # Exponential backoff: 1s, 2s, 4s
                get_logger().info("Retrying in %d seconds...", sleep_time)
                time.sleep(sleep_time)
            else:
                raise RuntimeError(
                    f"Failed to download {output_path.name} after {max_retries} attempts. "
                    f"Last error: {e}"
                )


def _download_and_validate_file(file_entry: ToolchainFile, dest_dir: Path) -> Path:
    """
    Download and validate a single toolchain file.

    Args:
        file_entry: File entry dict with 'url', 'filename', 'sha256', 'sequence'
        dest_dir: Destination directory

    Returns:
        Path: Path to validated file

    Raises:
        RuntimeError: If download or validation fails
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    file_path = dest_dir / file_entry["filename"]
    url = file_entry["url"]
    expected_sha256 = file_entry.get("sha256", "")

    # Check if file exists
    if file_path.exists():
        get_logger().info("File exists: %s", file_entry["filename"])

        # Validate checksum if provided
        if expected_sha256:
            get_logger().info("Verifying checksum: %s", file_entry["filename"])
            actual_sha256 = _compute_sha256(file_path)

            if actual_sha256.lower() == expected_sha256.lower():
                get_logger().info(
                    "File already valid, skipping download: %s", file_entry["filename"]
                )
                return file_path
            else:
                get_logger().warning(
                    "Checksum mismatch for %s. Expected: %s, Got: %s",
                    file_entry["filename"],
                    expected_sha256,
                    actual_sha256,
                )
                get_logger().info(
                    "Deleting and re-downloading: %s", file_entry["filename"]
                )
                file_path.unlink()
        else:
            get_logger().warning(
                "File exists but no checksum available, using existing: %s",
                file_entry["filename"],
            )
            return file_path

    # Download file
    get_logger().info("Downloading: %s", file_entry["filename"])
    _download_with_retry(url, file_path)

    # Validate checksum if provided
    if expected_sha256:
        get_logger().info("Verifying downloaded file: %s", file_entry["filename"])
        actual_sha256 = _compute_sha256(file_path)

        if actual_sha256.lower() != expected_sha256.lower():
            raise RuntimeError(
                f"Checksum validation failed for {file_entry['filename']} after download. "
                f"Expected: {expected_sha256}, Got: {actual_sha256}. "
                f"The downloaded file may be corrupted or the checksum in win_toolchain.json "
                f"may be incorrect."
            )

        get_logger().info("Checksum verified: %s", file_entry["filename"])
    else:
        get_logger().warning(
            "No checksum available for %s, skipping validation", file_entry["filename"]
        )

    return file_path


def _merge_tar_files(tar_files, dest_dir):
    """
    Merge tar split files using cat and tar commands

    Args:
        tar_files: List of Path objects for tar split files
        dest_dir: Directory to extract to

    Raises:
        RuntimeError: If merge fails or output file not created
    """
    if not tar_files:
        raise RuntimeError("No tar files provided for merging")

    # Sort files to ensure correct order (.001, .002, .003, ...)
    tar_files = sorted(tar_files, key=lambda p: p.name)

    get_logger().info("Merging %d tar files...", len(tar_files))
    for tar_file in tar_files:
        get_logger().info("  - %s", tar_file.name)

    try:
        # Merge tar files using cat and tar
        # Command: cat file.tar.001 file.tar.002 ... | tar xvf - -C dest_dir
        cat_cmd = ["cat"] + [str(f) for f in tar_files]
        tar_cmd = ["tar", "xvf", "-", "-C", str(dest_dir)]

        get_logger().info("Running: %s | %s", " ".join(cat_cmd), " ".join(tar_cmd))

        # Run cat process
        cat_process = subprocess.Popen(
            cat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        # Run tar process with cat output as input
        tar_process = subprocess.Popen(
            tar_cmd,
            stdin=cat_process.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Allow cat_process to receive SIGPIPE if tar_process exits
        cat_process.stdout.close()

        # Wait for tar to complete
        tar_stdout, tar_stderr = tar_process.communicate()

        # Check tar process return code
        if tar_process.returncode != 0:
            tar_stderr_str = tar_stderr.decode(ENCODING) if tar_stderr else ""
            raise RuntimeError(
                f"Tar extraction failed with code {tar_process.returncode}. "
                f"Error: {tar_stderr_str}"
            )

        # Check cat process return code
        cat_process.wait()
        if cat_process.returncode != 0:
            raise RuntimeError(
                f"Cat merge failed with code {cat_process.returncode}. "
                "One or more tar files may be corrupted or inaccessible."
            )

        get_logger().info("Tar files merged successfully")

    except FileNotFoundError as e:
        raise RuntimeError(
            f"Required command not found: {e}. "
            "Please ensure cat and tar are installed and in PATH."
        )
    except Exception as e:
        raise RuntimeError(f"Failed to merge tar files: {e}")


def _download_github_toolchain(
    chromium_version, sdk_version, dest_dir, zip_filename, sha512, files
):
    """
    Download Windows toolchain from configuration

    Downloads tar files specified in configuration, validates checksums,
    and merges them into the destination directory.
    If the final zip file already exists with valid checksum, skips download.

    Args:
        chromium_version: Chromium version matching release tag (e.g., '144.0.7559.96')
        sdk_version: SDK version for logging/context (e.g., '10.0.26100.0')
        dest_dir: Destination directory
        zip_filename: Expected zip filename without extension (e.g., '16b53d08e9')
        sha512: Expected SHA512 checksum of the final zip file
        files: List of file entries from configuration (already variable-substituted)

    Raises:
        RuntimeError: If download or validation fails
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    get_logger().info("Starting toolchain download...")
    get_logger().info("Chromium version: %s", chromium_version)
    get_logger().info("SDK version: %s", sdk_version)
    get_logger().info("Destination: %s", dest_dir)
    get_logger().info("Files to download: %d", len(files))

    # Check if zip file already exists with valid checksum
    zip_path = dest_dir / f"{zip_filename}.zip"
    if _validate_zip_file(zip_path, sha512):
        get_logger().info("Valid toolchain zip already exists, skipping download")
        return

    # If zip exists but validation failed, delete it
    if zip_path.exists():
        get_logger().info("Deleting invalid zip file: %s", zip_path.name)
        zip_path.unlink()

    # Sort files by sequence number (trust JSON order but verify)
    sorted_files = sorted(files, key=lambda f: f["sequence"])

    # Log file download order
    get_logger().info("Download order (by sequence):")
    for file_entry in sorted_files:
        get_logger().info("  [%d] %s", file_entry["sequence"], file_entry["filename"])

    # Download and validate each file
    validated_file_paths = []
    for i, file_entry in enumerate(sorted_files, start=1):
        get_logger().info(
            "Processing file %d/%d (sequence #%d): %s",
            i,
            len(sorted_files),
            file_entry["sequence"],
            file_entry["filename"],
        )

        try:
            file_path = _download_and_validate_file(file_entry, dest_dir)
            validated_file_paths.append(file_path)
        except RuntimeError as e:
            raise RuntimeError(
                f"Failed to download or validate {file_entry['filename']}: {e}"
            )

    get_logger().info(
        "All %d tar files validated successfully", len(validated_file_paths)
    )

    # Merge tar files
    _merge_tar_files(validated_file_paths, dest_dir)

    # Validate final zip file
    if not _validate_zip_file(zip_path, sha512):
        raise RuntimeError(
            f"Final zip file validation failed: {zip_path}. "
            f"The extracted zip may be corrupted or the SHA512 in win_toolchain.json is incorrect. "
            f"Please verify the SHA512 checksum."
        )

    get_logger().info("Toolchain download complete")


def _read_toolchain_config(target_arch="x64"):
    """
    Read Windows toolchain configuration from win_toolchain.json

    Args:
        target_arch: Target architecture ('x64', 'x86', or 'arm64')

    Returns:
        dict: Dictionary with keys: 'chromium_version', 'zip_filename', 'sha512', 'files'

    Raises:
        RuntimeError: If config file missing or invalid
    """
    config_file = _ROOT_DIR / "win_toolchain.json"

    if not config_file.exists():
        raise RuntimeError(
            f"Windows toolchain configuration not found: {config_file}. "
            "Please create win_toolchain.json with toolchain sections."
        )

    # Load JSON
    try:
        config_data = json.loads(config_file.read_text(encoding=ENCODING))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON in {config_file}: {e}")

    # Validate variables section exists
    if "variables" not in config_data:
        raise RuntimeError(
            f"Invalid config: 'variables' section missing in {config_file}"
        )

    variables = config_data["variables"]
    if not isinstance(variables, dict) or len(variables) == 0:
        raise RuntimeError(
            f"Invalid config: 'variables' must be a non-empty dictionary"
        )

    # Select section based on architecture
    if target_arch in ("x64", "x86"):
        section = "win-toolchain-noarm"
    else:
        # arm64
        section = "win-toolchain"

    # Validate section
    _validate_toolchain_config(config_data, section)

    section_data = config_data[section]

    # Extract chromium_version from variables
    chromium_version = variables.get("chromium_version")
    if not chromium_version:
        raise RuntimeError(
            "Invalid config: 'chromium_version' not found in variables section"
        )

    # Perform variable substitution on file entries
    substituted_files = []
    for file_entry in section_data["files"]:
        try:
            substituted_file = {
                "sequence": file_entry["sequence"],
                "url": _substitute_variables(file_entry["url"], variables),
                "filename": _substitute_variables(file_entry["filename"], variables),
                "sha256": file_entry["sha256"],
            }
            substituted_files.append(substituted_file)
        except RuntimeError as e:
            raise RuntimeError(
                f"Failed to process file entry (sequence={file_entry.get('sequence', '?')}): {e}"
            )

    # Build result dict
    result = {
        "chromium_version": chromium_version,
        "zip_filename": section_data["zip_filename"],
        "sha512": section_data["sha512"],
        "files": substituted_files,  # Files with variables substituted
    }

    get_logger().info(
        "Loaded toolchain config from [%s] for %s: version=%s, zip=%s.zip, files=%d",
        section,
        target_arch,
        result["chromium_version"],
        result["zip_filename"],
        len(result["files"]),
    )

    return result


def _extract_vs_toolchain_info(vs_toolchain_path):
    """
    Extract toolchain information from vs_toolchain.py file

    Args:
        vs_toolchain_path: Path object of the vs_toolchain.py file

    Returns:
        dict: Dictionary containing extracted information in the format:
            {
                'toolchain_hash': str,  # e.g. 'e4305f407e'
                'sdk_version': str,     # e.g. '10.0.26100.0'
            }

    Raises:
        RuntimeError: If the file does not exist or required information cannot be extracted
    """
    if not vs_toolchain_path.exists():
        raise RuntimeError(f"vs_toolchain.py not found at {vs_toolchain_path}")

    content = vs_toolchain_path.read_text(encoding=ENCODING)

    # Define variables to extract and their regex patterns
    patterns = {
        "toolchain_hash": r'TOOLCHAIN_HASH\s*=\s*[\'"]([a-f0-9]+)[\'"]',
        "sdk_version": r'SDK_VERSION\s*=\s*[\'"]([0-9.]+)[\'"]',
    }

    result = {}

    # Extract all variables
    for key, pattern in patterns.items():
        match = re.search(pattern, content)
        if not match:
            raise RuntimeError(
                f"Could not extract {key.upper()} from {vs_toolchain_path}. "
                f"Pattern expected: {key.upper()} = '<value>'"
            )
        result[key] = match.group(1)
        get_logger().info("Extracted %s: %s", key.upper(), result[key])

    return result


def setup_windows_toolchain(source_tree, ci_mode=False):
    """
    Configure Windows Toolchain environment.

    This function performs two main steps:
    1. Download Visual Studio toolchain from GitHub (if not cached)
    2. Run vs_toolchain.py to extract and configure the toolchain

    Args:
        source_tree: Path object of the source directory (build/src)
        ci_mode: Boolean indicating if running in CI mode (enables stamp-based skipping)
    """
    # Detect target architecture from command-line arguments
    target_arch = get_target_arch_from_args()
    get_logger().info("Setting up Windows Toolchain for architecture: %s", target_arch)

    # Extract toolchain hash and SDK version from vs_toolchain.py
    # These are needed to identify the correct toolchain version to download
    vs_toolchain_path = source_tree / "build" / "vs_toolchain.py"
    toolchain_info = _extract_vs_toolchain_info(vs_toolchain_path)
    toolchain_hash = toolchain_info["toolchain_hash"]
    sdk_version = toolchain_info["sdk_version"]

    # Read toolchain configuration (Chromium version, zip filename, SHA512)
    # from win_toolchain.json based on target architecture
    toolchain_config = _read_toolchain_config(target_arch)

    # Toolchain will be downloaded to build/src/third_party/win_toolchain/
    toolchain_dir = _ROOT_DIR / "build/src/third_party/win_toolchain"

    # Download VS toolchain from GitHub
    download_stamp = f".download_vs_toolchain_{target_arch}.stamp"
    if should_skip_step(source_tree, download_stamp, ci_mode):
        get_logger().info("Skipping VS toolchain download (already completed)")
    else:
        get_logger().info("Downloading VS toolchain from GitHub...")

        # Download ciopfs utility if not present (required for case-insensitive operations)
        if not (source_tree / "build/ciopfs").exists():
            get_logger().info("Downloading ciopfs utility...")
            download_from_sha1(
                sha1_file=source_tree / "build" / "ciopfs.sha1",
                output_file=source_tree / "build" / "ciopfs",
                bucket="chromium-browser-clang/ciopfs",
            )

        # Download toolchain files from configuration and merge into zip
        _download_github_toolchain(
            chromium_version=toolchain_config["chromium_version"],
            sdk_version=sdk_version,
            dest_dir=toolchain_dir,
            zip_filename=toolchain_config["zip_filename"],
            sha512=toolchain_config["sha512"],
            files=toolchain_config["files"],
        )

        mark_step_complete(source_tree, download_stamp)
        get_logger().info("VS toolchain download completed")

    # Extract and configure the toolchain using vs_toolchain.py
    extraction_stamp = f".vs_toolchain_updated_{target_arch}.stamp"
    extraction_stamp_path = source_tree.parent
    if should_skip_step(extraction_stamp_path, extraction_stamp, ci_mode):
        get_logger().info("Skipping VS toolchain extraction (already completed)")
    else:
        get_logger().info("Extracting and configuring VS toolchain...")

        # Set environment variables for vs_toolchain.py
        os.environ["DEPOT_TOOLS_WIN_TOOLCHAIN_BASE_URL"] = str(toolchain_dir)
        os.environ[f"GYP_MSVS_HASH_{toolchain_hash}"] = toolchain_config["zip_filename"]

        get_logger().info("Set DEPOT_TOOLS_WIN_TOOLCHAIN_BASE_URL=%s", toolchain_dir)
        get_logger().info(
            "Set GYP_MSVS_HASH_%s=%s", toolchain_hash, toolchain_config["zip_filename"]
        )

        # Run vs_toolchain.py update --force
        # This extracts the toolchain and sets up the build environment
        get_logger().info("Running vs_toolchain.py update --force")
        run_build_process(sys.executable, str(vs_toolchain_path), "update", "--force")

        mark_step_complete(extraction_stamp_path, extraction_stamp)
        get_logger().info("VS toolchain extraction completed")

    get_logger().info("Windows Toolchain setup completed successfully")
