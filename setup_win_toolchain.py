#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 The ungoogled-chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
GitHub toolchain downloader for Windows builds

Downloads Windows toolchain split tar files from GitHub releases,
validates checksums, and merges them into a zip file.
"""

import configparser
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from build_common import run_build_process, should_skip_step, mark_step_complete, get_target_arch_from_args
from setup_utils import download_from_sha1

sys.path.insert(0, str(Path(__file__).resolve().parent / 'ungoogled-chromium' / 'utils'))
from _common import ENCODING, get_logger

sys.path.pop(0)

# Constants
_ROOT_DIR = Path(__file__).resolve().parent
GITHUB_API_BASE = 'https://api.github.com'
GITHUB_REPO = 'vpday/chromium-win-toolchain-builder'


def _fetch_github_release_assets(chromium_version):
    """
    Fetch release assets from GitHub API

    Args:
        chromium_version: Release tag matching Chromium version (e.g., '144.0.7559.96')

    Returns:
        list: List of asset dicts with keys: 'name', 'browser_download_url', 'digest'

    Raises:
        RuntimeError: If release not found or API request fails
    """
    url = f'{GITHUB_API_BASE}/repos/{GITHUB_REPO}/releases/tags/{chromium_version}'
    get_logger().info('Fetching GitHub release: %s', url)

    try:
        request = urllib.request.Request(
            url,
            headers={
                'Accept': 'application/vnd.github+json',
                'User-Agent': 'ungoogled-chromium-build'
            }
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode(ENCODING))

        assets = []
        for asset in data.get('assets', []):
            # Extract SHA256 from digest field (format: "sha256:hash")
            digest = asset.get('digest', '')
            sha256_hash = None
            if digest.startswith('sha256:'):
                sha256_hash = digest.split(':', 1)[1]

            try:
                assets.append({
                    'name': asset['name'],
                    'browser_download_url': asset['browser_download_url'],
                    'size': asset['size'],
                    'sha256': sha256_hash
                })
            except KeyError as e:
                raise RuntimeError(
                    f'GitHub API returned incomplete asset data: missing field {e}. '
                    f'Asset data: {asset}'
                )

        get_logger().info('Found %d assets in release', len(assets))
        return assets

    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(
                f'GitHub release not found for version {chromium_version}. '
                f'Please verify the release exists at: '
                f'https://github.com/{GITHUB_REPO}/releases/tag/{chromium_version}'
            )
        raise RuntimeError(f'GitHub API error: HTTP {e.code} {e.reason}')
    except urllib.error.URLError as e:
        raise RuntimeError(f'Network error while fetching GitHub release: {e.reason}')
    except Exception as e:
        raise RuntimeError(f'Failed to fetch GitHub release: {e}') from e


def _compute_hash(file_path, algorithm='sha256'):
    """
    Compute hash checksum of a file

    Args:
        file_path: Path to the file
        algorithm: Hash algorithm name ('sha256', 'sha512', etc.)

    Returns:
        str: Hexadecimal hash checksum
    """
    hasher = hashlib.new(algorithm)
    with open(file_path, 'rb') as f:
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
    return _compute_hash(file_path, 'sha256')


def _compute_sha512(file_path):
    """
    Compute SHA512 checksum of a file

    Args:
        file_path: Path to the file

    Returns:
        str: Hexadecimal SHA512 checksum
    """
    return _compute_hash(file_path, 'sha512')


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
        get_logger().info('Zip file does not exist: %s', zip_path)
        return False

    get_logger().info('Validating zip file checksum: %s', zip_path.name)
    actual_sha512 = _compute_sha512(zip_path)

    if actual_sha512.lower() == expected_sha512.lower():
        get_logger().info('Zip file validation passed')
        return True
    else:
        get_logger().warning(
            'Zip file checksum mismatch. Expected: %s, Got: %s',
            expected_sha512, actual_sha512
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
            get_logger().info('Downloading (attempt %d/%d): %s', attempt + 1, max_retries, output_path.name)
            urllib.request.urlretrieve(url, str(output_path))
            get_logger().info('Download complete: %s', output_path.name)
            return
        except Exception as e:
            get_logger().warning('Download failed (attempt %d/%d): %s', attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                sleep_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                get_logger().info('Retrying in %d seconds...', sleep_time)
                time.sleep(sleep_time)
            else:
                raise RuntimeError(
                    f'Failed to download {output_path.name} after {max_retries} attempts. '
                    f'Last error: {e}'
                )


def _validate_and_redownload_assets(assets, dest_dir, asset_pattern):
    """
    Validate downloaded assets and re-download if checksums mismatch

    Args:
        assets: List of asset dicts from GitHub API
        dest_dir: Directory containing downloaded files
        asset_pattern: Pattern to filter assets (e.g., 'win_toolchain_*.tar.*')

    Returns:
        list: List of validated file paths

    Raises:
        RuntimeError: If validation fails after re-download
    """
    import fnmatch

    validated_files = []

    for asset in assets:
        asset_name = asset['name']

        # Filter by pattern
        if not fnmatch.fnmatch(asset_name, asset_pattern):
            continue

        file_path = dest_dir / asset_name
        expected_sha256 = asset.get('sha256')

        # Check if file exists
        if not file_path.exists():
            get_logger().info('File missing, downloading: %s', asset_name)
            _download_with_retry(asset['browser_download_url'], file_path)

        # Validate checksum if provided
        if expected_sha256:
            get_logger().info('Verifying checksum: %s', asset_name)
            actual_sha256 = _compute_sha256(file_path)

            if actual_sha256.lower() != expected_sha256.lower():
                get_logger().warning(
                    'Checksum mismatch for %s. Expected: %s, Got: %s',
                    asset_name, expected_sha256, actual_sha256
                )
                get_logger().info('Deleting and re-downloading: %s', asset_name)
                file_path.unlink()
                _download_with_retry(asset['browser_download_url'], file_path)

                # Re-verify after download
                actual_sha256 = _compute_sha256(file_path)
                if actual_sha256.lower() != expected_sha256.lower():
                    raise RuntimeError(
                        f'Checksum validation failed for {asset_name} after re-download. '
                        f'Expected: {expected_sha256}, Got: {actual_sha256}'
                    )

            get_logger().info('Checksum verified: %s', asset_name)
        else:
            get_logger().warning('No checksum available for %s, skipping validation', asset_name)

        validated_files.append(file_path)

    if not validated_files:
        raise RuntimeError(f'No assets found matching pattern: {asset_pattern}')

    return validated_files


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
        raise RuntimeError('No tar files provided for merging')

    # Sort files to ensure correct order (.001, .002, .003, ...)
    tar_files = sorted(tar_files, key=lambda p: p.name)

    get_logger().info('Merging %d tar files...', len(tar_files))
    for tar_file in tar_files:
        get_logger().info('  - %s', tar_file.name)

    try:
        # Merge tar files using cat and tar
        # Command: cat file.tar.001 file.tar.002 ... | tar xvf - -C dest_dir
        cat_cmd = ['cat'] + [str(f) for f in tar_files]
        tar_cmd = ['tar', 'xvf', '-', '-C', str(dest_dir)]

        get_logger().info('Running: %s | %s', ' '.join(cat_cmd), ' '.join(tar_cmd))

        # Run cat process
        cat_process = subprocess.Popen(
            cat_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Run tar process with cat output as input
        tar_process = subprocess.Popen(
            tar_cmd,
            stdin=cat_process.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Allow cat_process to receive SIGPIPE if tar_process exits
        cat_process.stdout.close()

        # Wait for tar to complete
        tar_stdout, tar_stderr = tar_process.communicate()

        # Check tar process return code
        if tar_process.returncode != 0:
            tar_stderr_str = tar_stderr.decode(ENCODING) if tar_stderr else ''
            raise RuntimeError(
                f'Tar extraction failed with code {tar_process.returncode}. '
                f'Error: {tar_stderr_str}'
            )

        # Check cat process return code
        cat_process.wait()
        if cat_process.returncode != 0:
            raise RuntimeError(
                f'Cat merge failed with code {cat_process.returncode}. '
                'One or more tar files may be corrupted or inaccessible.'
            )

        get_logger().info('Tar files merged successfully')

    except FileNotFoundError as e:
        raise RuntimeError(
            f'Required command not found: {e}. '
            'Please ensure cat and tar are installed and in PATH.'
        )
    except Exception as e:
        raise RuntimeError(f'Failed to merge tar files: {e}')


def _download_github_toolchain(chromium_version, sdk_version, dest_dir, zip_filename, sha512):
    """
    Download Windows toolchain from GitHub releases

    Downloads tar split files from vpday/chromium-win-toolchain-builder,
    validates checksums, and merges them into the destination directory.
    If the final zip file already exists with valid checksum, skips download.

    Args:
        chromium_version: Chromium version matching release tag (e.g., '144.0.7559.96')
        sdk_version: SDK version for filename pattern (e.g., '10.0.26100.0')
        dest_dir: Destination directory
        zip_filename: Expected zip filename without extension (e.g., '16b53d08e9')
        sha512: Expected SHA512 checksum of the final zip file

    Raises:
        RuntimeError: If release not found or download fails
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    get_logger().info('Starting GitHub toolchain download...')
    get_logger().info('Chromium version: %s', chromium_version)
    get_logger().info('SDK version: %s', sdk_version)
    get_logger().info('Destination: %s', dest_dir)

    # Check if zip file already exists with valid checksum
    zip_path = dest_dir / f'{zip_filename}.zip'
    if _validate_zip_file(zip_path, sha512):
        get_logger().info('Valid toolchain zip already exists, skipping download')
        return

    # If zip exists but validation failed, delete it
    if zip_path.exists():
        get_logger().info('Deleting invalid zip file: %s', zip_path.name)
        zip_path.unlink()

    # Fetch release information from GitHub API
    assets = _fetch_github_release_assets(chromium_version)

    # Build asset pattern
    asset_pattern = f'win_toolchain_chromium-{chromium_version}_vs-2022_sdk-{sdk_version}.tar.*'
    get_logger().info('Looking for assets matching: %s', asset_pattern)

    # Download and validate all matching assets
    validated_files = _validate_and_redownload_assets(assets, dest_dir, asset_pattern)

    get_logger().info('All %d tar files validated successfully', len(validated_files))

    # Merge tar files
    _merge_tar_files(validated_files, dest_dir)

    # Validate final zip file
    if not _validate_zip_file(zip_path, sha512):
        raise RuntimeError(
            f'Final zip file validation failed: {zip_path}. '
            f'The extracted zip may be corrupted or the SHA512 in win_toolchain_downloads.ini is incorrect. '
            f'Please verify the SHA512 checksum.'
        )

    get_logger().info('GitHub toolchain download complete')


def _read_toolchain_config(target_arch='x64'):
    """
    Read Windows toolchain configuration from win_toolchain_downloads.ini

    Args:
        target_arch: Target architecture ('x64', 'x86', or 'arm64')

    Returns:
        dict: Dictionary with keys: 'chromium_version', 'zip_filename', 'sha512'

    Raises:
        RuntimeError: If config file missing or invalid
    """
    config_file = _ROOT_DIR / 'win_toolchain_downloads.ini'

    if not config_file.exists():
        raise RuntimeError(
            f'Windows toolchain configuration not found: {config_file}. '
            'Please create win_toolchain_downloads.ini with [win-toolchain] section.'
        )

    config = configparser.ConfigParser()
    config.read(config_file, encoding=ENCODING)

    # Select section based on architecture
    if target_arch in ('x64', 'x86'):
        section = 'win-toolchain-noarm'
    else:
        # arm64
        section = 'win-toolchain'

    # Verify section exists
    if not config.has_section(section):
        available = ', '.join([f'[{s}]' for s in config.sections()])
        raise RuntimeError(
            f'Invalid config: [{section}] section missing in {config_file}. '
            f'Required for {target_arch} builds. Available sections: {available}'
        )

    required_keys = ['chromium_version', 'zip_filename', 'sha512']
    result = {}

    for key in required_keys:
        if not config.has_option(section, key):
            raise RuntimeError(
                f'Invalid config: {key} missing in [{section}] section'
            )
        result[key] = config.get(section, key)

    get_logger().info('Loaded toolchain config from [%s] for %s: version=%s, zip=%s.zip',
                      section, target_arch, result['chromium_version'], result['zip_filename'])

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
        raise RuntimeError(f'vs_toolchain.py not found at {vs_toolchain_path}')

    content = vs_toolchain_path.read_text(encoding=ENCODING)

    # Define variables to extract and their regex patterns
    patterns = {
        'toolchain_hash': r'TOOLCHAIN_HASH\s*=\s*[\'"]([a-f0-9]+)[\'"]',
        'sdk_version': r'SDK_VERSION\s*=\s*[\'"]([0-9.]+)[\'"]',
    }

    result = {}

    # Extract all variables
    for key, pattern in patterns.items():
        match = re.search(pattern, content)
        if not match:
            raise RuntimeError(
                f'Could not extract {key.upper()} from {vs_toolchain_path}. '
                f'Pattern expected: {key.upper()} = \'<value>\''
            )
        result[key] = match.group(1)
        get_logger().info('Extracted %s: %s', key.upper(), result[key])

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
    get_logger().info('Setting up Windows Toolchain for architecture: %s', target_arch)

    # Extract toolchain hash and SDK version from vs_toolchain.py
    # These are needed to identify the correct toolchain version to download
    vs_toolchain_path = source_tree / 'build' / 'vs_toolchain.py'
    toolchain_info = _extract_vs_toolchain_info(vs_toolchain_path)
    toolchain_hash = toolchain_info["toolchain_hash"]
    sdk_version = toolchain_info["sdk_version"]

    # Read toolchain configuration (Chromium version, zip filename, SHA512)
    # from win_toolchain_downloads.ini based on target architecture
    toolchain_config = _read_toolchain_config(target_arch)

    # Toolchain will be downloaded to build/src/third_party/win_toolchain/
    toolchain_dir = _ROOT_DIR / 'build/src/third_party/win_toolchain'

    # Download VS toolchain from GitHub
    download_stamp = f'.download_vs_toolchain_{target_arch}.stamp'
    if should_skip_step(source_tree, download_stamp, ci_mode):
        get_logger().info('Skipping VS toolchain download (already completed)')
    else:
        get_logger().info('Downloading VS toolchain from GitHub...')

        # Download ciopfs utility if not present (required for case-insensitive operations)
        if not (source_tree / 'build/ciopfs').exists():
            get_logger().info('Downloading ciopfs utility...')
            download_from_sha1(
                sha1_file=source_tree / 'build' / 'ciopfs.sha1',
                output_file=source_tree / 'build' / 'ciopfs',
                bucket='chromium-browser-clang/ciopfs'
            )

        # Download toolchain split tar files from GitHub and merge into zip
        _download_github_toolchain(
            chromium_version=toolchain_config['chromium_version'],
            sdk_version=sdk_version,
            dest_dir=toolchain_dir,
            zip_filename=toolchain_config['zip_filename'],
            sha512=toolchain_config['sha512']
        )

        mark_step_complete(source_tree, download_stamp)
        get_logger().info('VS toolchain download completed')

    # Extract and configure the toolchain using vs_toolchain.py
    extraction_stamp = f'.vs_toolchain_updated_{target_arch}.stamp'
    extraction_stamp_path = source_tree.parent
    if should_skip_step(extraction_stamp_path, extraction_stamp, ci_mode):
        get_logger().info('Skipping VS toolchain extraction (already completed)')
    else:
        get_logger().info('Extracting and configuring VS toolchain...')

        # Set environment variables for vs_toolchain.py
        os.environ['DEPOT_TOOLS_WIN_TOOLCHAIN_BASE_URL'] = str(toolchain_dir)
        os.environ[f'GYP_MSVS_HASH_{toolchain_hash}'] = toolchain_config['zip_filename']

        get_logger().info('Set DEPOT_TOOLS_WIN_TOOLCHAIN_BASE_URL=%s', toolchain_dir)
        get_logger().info('Set GYP_MSVS_HASH_%s=%s', toolchain_hash, toolchain_config['zip_filename'])

        # Run vs_toolchain.py update --force
        # This extracts the toolchain and sets up the build environment
        get_logger().info('Running vs_toolchain.py update --force')
        run_build_process(
            sys.executable,
            str(vs_toolchain_path),
            'update',
            '--force'
        )

        mark_step_complete(extraction_stamp_path, extraction_stamp)
        get_logger().info('VS toolchain extraction completed')

    get_logger().info('Windows Toolchain setup completed successfully')
