#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 The ungoogled-chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
Rust toolchain management for ungoogled-chromium Windows build.

This module provides Rust toolchain setup and management utilities including:
- Multi-architecture Rust toolchain installation
- Architecture-specific library management
- Host/target architecture handling
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'ungoogled-chromium' / 'utils'))
from _common import ENCODING, get_logger

sys.path.pop(0)


def fix_top_level_libs(lib_dir, host_arch):
    """
    Fix architecture-specific library files in the top-level lib directory

    Ensure the top-level lib directory contains only libraries for the host architecture,
    not overwritten by other architectures

    Args:
        lib_dir: Path object of the lib directory
        host_arch: Host architecture ('x86_64', 'i686', 'aarch64')
    """
    get_logger().info('Fixing top-level lib directory for host architecture: %s', host_arch)

    # Find libraries for the corresponding architecture in the rustlib directory
    rustlib_host_lib = lib_dir / 'rustlib' / f'{host_arch}-unknown-linux-gnu' / 'lib'

    if not rustlib_host_lib.exists():
        get_logger().warning('rustlib host lib not found: %s', rustlib_host_lib)
        return

    # Library file patterns to copy from rustlib to top level
    lib_patterns = [
        'libLLVM*.so*',
        'libstd*.so*',
        'librustc_driver*.so*',
    ]

    for pattern in lib_patterns:
        for lib_file in rustlib_host_lib.glob(pattern):
            target_file = lib_dir / lib_file.name

            # Check if target file exists and architecture doesn't match
            if target_file.exists():
                # Verify architecture
                try:
                    result = subprocess.run(
                        ['file', str(target_file)],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        encoding='utf-8',
                        timeout=5
                    )

                    file_output = result.stdout.lower()

                    # Check if architecture matches
                    arch_matches = {
                        'x86_64': 'x86-64' in file_output or 'x86_64' in file_output,
                        'i686': 'intel 80386' in file_output or 'i386' in file_output or 'i686' in file_output,
                        'aarch64': 'aarch64' in file_output or 'arm64' in file_output,
                    }

                    if not arch_matches.get(host_arch, False):
                        get_logger().warning(
                            'Architecture mismatch for %s (expected %s, found: %s). Replacing with correct version.',
                            target_file.name, host_arch, file_output.strip()
                        )
                        target_file.unlink()
                    else:
                        # Architecture matches, skip
                        continue
                except Exception as e:
                    get_logger().warning('Failed to verify architecture for %s: %s', target_file, e)

            # Copy or create symbolic link
            if lib_file.is_symlink():
                # Read symbolic link target
                link_target = os.readlink(str(lib_file))

                # If it's a relative path, keep it relative
                if not os.path.isabs(link_target):
                    target_file.symlink_to(link_target)
                    get_logger().info('Created symlink: %s -> %s', target_file, link_target)
                else:
                    # Absolute path needs to be recalculated
                    shutil.copy2(lib_file, target_file, follow_symlinks=True)
                    get_logger().info('Copied (following symlink): %s -> %s', lib_file, target_file)
            else:
                # Regular file, copy directly
                shutil.copy2(lib_file, target_file)
                get_logger().info('Copied: %s -> %s', lib_file, target_file)


def setup_rust_toolchain(source_tree, ci_mode=False):
    """
    Set up Rust toolchain with multi-architecture support.

    This function handles the complex Rust toolchain setup for cross-compilation,
    managing x86_64, i686, and aarch64 toolchains simultaneously.

    Args:
        source_tree: Path object of the source directory
        ci_mode: Boolean indicating if running in CI mode (skip if already installed)

    Returns:
        Path: Path to the Rust toolchain directory
    """
    # Check if rust-toolchain folder has been populated
    host_cpu_is_64_bit = sys.maxsize > 2 ** 32
    rust_dir_dst = source_tree / 'third_party' / 'rust-toolchain'
    rust_dir_src64 = source_tree / 'third_party' / 'rust-toolchain-x64'
    rust_dir_src86 = source_tree / 'third_party' / 'rust-toolchain-x86'
    rust_dir_srcarm = source_tree / 'third_party' / 'rust-toolchain-arm'
    rust_flag_file = rust_dir_dst / 'INSTALLED_VERSION'

    if ci_mode and rust_flag_file.exists():
        return rust_dir_dst

    get_logger().info('Setting up Rust toolchain with multi-architecture support...')

    # Define architecture mappings
    arch_configs = {
        'x86_64': {
            'source_dir': rust_dir_src64,
            'target_subdir': 'x86_64',
            'is_host': host_cpu_is_64_bit,
        },
        'i686': {
            'source_dir': rust_dir_src86,
            'target_subdir': 'i686',
            'is_host': not host_cpu_is_64_bit,
        },
        'aarch64': {
            'source_dir': rust_dir_srcarm,
            'target_subdir': 'aarch64',
            'is_host': False,  # ARM64 is typically not the host machine
        },
    }

    # Determine host architecture
    host_arch = None
    for arch, config in arch_configs.items():
        if config['is_host']:
            host_arch = arch
            break

    if not host_arch:
        get_logger().error('Unable to determine host architecture')
        sys.exit(1)

    get_logger().info('Host architecture: %s', host_arch)

    # Create necessary target directories before processing any architecture
    rust_dir_dst.mkdir(parents=True, exist_ok=True)
    (rust_dir_dst / 'bin').mkdir(parents=True, exist_ok=True)
    (rust_dir_dst / 'lib').mkdir(parents=True, exist_ok=True)
    get_logger().info('Created target directories: %s', rust_dir_dst)

    # Copy toolchain for each architecture to separate directories
    successful_archs = []  # Track successfully processed architectures

    for arch, config in arch_configs.items():
        source_dir = config['source_dir']
        target_subdir = config['target_subdir']
        is_host = config['is_host']

        get_logger().info('Processing %s architecture from %s', arch, source_dir)

        # Check if source directory exists
        if not source_dir.exists():
            get_logger().warning('Source directory not found: %s, skipping %s', source_dir, arch)
            continue

        rustc_dir = source_dir / 'rustc'

        if not rustc_dir.exists():
            get_logger().warning('rustc directory not found in %s, skipping %s', source_dir, arch)
            continue

        # Validate required subdirectories
        required_subdirs = ['bin', 'lib']
        missing_subdirs = [d for d in required_subdirs if not (rustc_dir / d).exists()]

        if missing_subdirs:
            get_logger().warning(
                'Missing required subdirectories in %s: %s, skipping %s',
                rustc_dir, missing_subdirs, arch
            )
            continue

        get_logger().info('Found valid rustc at: %s', rustc_dir)

        # If it's the host architecture, copy to top-level directories
        if is_host:
            get_logger().info('Copying host architecture (%s) to top-level directories', arch)

            # Copy bin directory
            bin_src = rustc_dir / 'bin'
            bin_dst = rust_dir_dst / 'bin'
            if bin_src.exists():
                if bin_dst.exists():
                    shutil.rmtree(bin_dst)
                shutil.copytree(bin_src, bin_dst, symlinks=True)
                get_logger().info('Copied bin: %s -> %s', bin_src, bin_dst)

            # Copy lib directory
            lib_src = rustc_dir / 'lib'
            lib_dst = rust_dir_dst / 'lib'
            if lib_src.exists():
                if lib_dst.exists():
                    shutil.rmtree(lib_dst)
                shutil.copytree(lib_src, lib_dst, symlinks=True)
                get_logger().info('Copied lib: %s -> %s', lib_src, lib_dst)

                # Fix architecture-specific libraries in top-level lib directory
                fix_top_level_libs(lib_dst, arch)

        # Also copy to architecture-specific subdirectories
        arch_target_dir = rust_dir_dst / target_subdir
        arch_target_dir.mkdir(parents=True, exist_ok=True)

        if is_host:
            # Host architecture: create symbolic links to top-level directories
            for subdir in ['bin', 'lib']:
                link_path = arch_target_dir / subdir
                target_path = Path('..') / subdir

                if link_path.exists() or link_path.is_symlink():
                    if link_path.is_symlink():
                        link_path.unlink()
                    elif link_path.is_dir():
                        shutil.rmtree(link_path)
                    else:
                        link_path.unlink()

                link_path.symlink_to(target_path)
                get_logger().info('Created symlink: %s -> %s', link_path, target_path)
        else:
            # Non-host architecture: copy directly
            for subdir in ['bin', 'lib']:
                src_dir = rustc_dir / subdir
                dst_dir = arch_target_dir / subdir

                if src_dir.exists():
                    if dst_dir.exists():
                        shutil.rmtree(dst_dir)
                    shutil.copytree(src_dir, dst_dir, symlinks=True)
                    get_logger().info('Copied %s for %s: %s -> %s', subdir, arch, src_dir, dst_dir)

        # Record successfully processed architecture
        successful_archs.append(arch)

    # Verify at least one architecture was successful
    if not successful_archs:
        get_logger().error(
            'Failed to process any architecture. Please check that Rust toolchains are properly downloaded.'
        )
        sys.exit(1)

    get_logger().info('Successfully processed architectures: %s', successful_archs)

    # Generate version file (ensure parent directory exists)
    get_logger().info('Generating Rust toolchain version file...')
    rustc_path = rust_dir_dst / 'bin' / 'rustc'

    if rustc_path.exists():
        try:

            # Execute rustc --version
            result = subprocess.run(
                [str(rustc_path), '--version'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8',
                timeout=10
            )

            if result.returncode == 0:
                rust_flag_file.write_text(result.stdout, encoding=ENCODING)
                get_logger().info('Rust version: %s', result.stdout.strip())
            else:
                raise RuntimeError(f'rustc failed with code {result.returncode}: {result.stderr}')

        except Exception as e:
            get_logger().warning('Failed to get rustc version: %s. Using placeholder.', e)
            rust_flag_file.write_text(
                f'rustc unknown version (host: {host_arch}, processed: {", ".join(successful_archs)})\n',
                encoding=ENCODING
            )
    else:
        get_logger().error('rustc binary not found at %s', rustc_path)
        rust_flag_file.write_text(
            f'rustc not installed (processed architectures: {", ".join(successful_archs)})\n',
            encoding=ENCODING
        )

    get_logger().info('Rust toolchain setup completed')

    return rust_dir_dst
