#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 The ungoogled-chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
Rust toolchain management for ungoogled-chromium Windows cross-compilation.

This module orchestrates the complex setup of Rust toolchains for building
Windows Chromium from a Linux host. It handles:

1. Multi-architecture support: x86_64, i686, and aarch64 toolchains
2. Component installation: rustc, cargo, rust-std, and optional tools
3. Directory layout: Consolidates toolchains into a unified structure
4. Host/target separation: Host tools at top level, target libs in subdirs
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

sys.path.insert(
    0, str(Path(__file__).resolve().parent / "ungoogled-chromium" / "utils")
)
from _common import ENCODING, get_logger

sys.path.pop(0)

# Configuration for Rust toolchain components to install
COMPONENTS_CONFIG = [
    {"name": "rustc", "has_bin": True, "has_lib": True, "required": True},
    {"name": "cargo", "has_bin": True, "has_lib": True, "required": True},
    {"name": "rust-std-{target}", "has_bin": False, "has_lib": True, "required": True},
    {
        "name": "llvm-tools-preview",
        "has_bin": False,
        "has_lib": True,
        "required": False,
    },
    {"name": "clippy-preview", "has_bin": True, "has_lib": True, "required": False},
    {"name": "rustfmt-preview", "has_bin": True, "has_lib": True, "required": False},
]


def _smart_copy(src: Path, dst: Path):
    """
    Intelligently copy a file or symlink, preserving symlink semantics.

    This function handles three cases:
    1. Regular file: Direct copy with metadata preservation
    2. Relative symlink: Recreate the symlink (stays relative)
    3. Absolute symlink: Resolve and copy the target file

    The destination is removed first if it exists to avoid conflicts.

    Args:
        src: Source file or symlink path
        dst: Destination path

    Note:
        Relative symlinks are preserved because they maintain correct
        references when the entire directory structure is copied together.
        Absolute symlinks are resolved to avoid breaking references to
        paths outside the toolchain directory.
    """
    # Clean up existing destination to avoid conflicts
    if dst.exists() or dst.is_symlink():
        try:
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        except OSError as e:
            get_logger().warning(f"Failed to remove existing destination {dst}: {e}")

    # Handle source based on its type
    if src.is_symlink():
        link_target = os.readlink(str(src))
        if not os.path.isabs(link_target):
            # Preserve relative symlinks - they'll work in the new location
            dst.symlink_to(link_target)
            get_logger().debug("Created symlink: %s -> %s", dst, link_target)
        else:
            # Resolve absolute symlinks to avoid external dependencies
            shutil.copy2(src, dst, follow_symlinks=True)
            get_logger().debug("Copied (following symlink): %s -> %s", src, dst)
    else:
        # Regular file: copy with metadata
        shutil.copy2(src, dst)
        get_logger().debug("Copied: %s -> %s", src, dst)


def _fix_top_level_libs(lib_dir: Path, host_arch: str):
    """
    Ensure top-level shared libraries match the host architecture.

    When merging multiple Rust toolchains, the top-level lib/ directory may
    contain shared libraries (.so files) from the wrong architecture if they
    were overwritten during the merge process. This function verifies and
    corrects the architecture of critical shared libraries.

    The correct versions are copied from:
        lib/rustlib/{host_arch}-unknown-linux-gnu/lib/*.so

    This is necessary because:
    1. The host's rustc/cargo binaries expect host-architecture libraries
    2. Later architectures might overwrite host libraries during merge
    3. Running mismatched libraries causes immediate crashes

    Args:
        lib_dir: Path to the top-level lib/ directory
        host_arch: Host architecture ('x86_64', 'i686', or 'aarch64')
    """
    get_logger().info(
        "Fixing top-level lib directory for host architecture: %s", host_arch
    )

    # Source: architecture-specific rustlib directory
    rustlib_host_lib = lib_dir / "rustlib" / f"{host_arch}-unknown-linux-gnu" / "lib"
    if not rustlib_host_lib.exists():
        get_logger().warning("rustlib host lib not found: %s", rustlib_host_lib)
        return

    # Critical shared libraries that must match host architecture
    lib_patterns = ["libLLVM*.so*", "libstd*.so*", "librustc_driver*.so*"]

    for pattern in lib_patterns:
        for lib_file in rustlib_host_lib.glob(pattern):
            target_file = lib_dir / lib_file.name

            # Verify existing file's architecture if present
            if target_file.exists():
                try:
                    result = subprocess.run(
                        ["file", str(target_file)],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    file_output = result.stdout.lower()

                    # Architecture detection patterns for the 'file' command
                    arch_matches = {
                        "x86_64": "x86-64" in file_output or "x86_64" in file_output,
                        "i686": "intel 80386" in file_output
                        or "i386" in file_output
                        or "i686" in file_output,
                        "aarch64": "aarch64" in file_output or "arm64" in file_output,
                    }

                    if not arch_matches.get(host_arch, False):
                        get_logger().warning(
                            "Architecture mismatch for %s. Replacing with correct version.",
                            target_file.name,
                        )
                        target_file.unlink()
                    else:
                        # Architecture matches, no need to replace
                        continue
                except Exception as e:
                    get_logger().warning(
                        "Failed to verify architecture for %s: %s", target_file, e
                    )

            # Copy the correct architecture version
            _smart_copy(lib_file, target_file)


def _merge_tree(src_dir: Path, dst_dir: Path):
    """
    Recursively merge a source directory tree into a destination directory.

    Unlike shutil.copytree(), this function merges into an existing directory
    rather than requiring the destination to be empty. Files with the same
    name are overwritten. This is essential for combining multiple Rust
    component directories (cargo, rustc, rust-std) into a single toolchain.

    Args:
        src_dir: Source directory to merge from
        dst_dir: Destination directory to merge into (created if needed)

    Note:
        Directories are merged recursively, while files and symlinks are
        copied using _smart_copy() to handle symlinks correctly.
    """
    if not dst_dir.exists():
        dst_dir.mkdir(parents=True, exist_ok=True)

    for item in src_dir.iterdir():
        dst_item = dst_dir / item.name

        if item.is_dir() and not item.is_symlink():
            # Recurse into subdirectories to merge their contents
            _merge_tree(item, dst_item)
        else:
            # Copy files and symlinks (symlinks are treated as files)
            _smart_copy(item, dst_item)


def _generate_version_file(rust_dir: Path, flag_file: Path, archs: List[str]):
    """
    Generate a version file to track the installed Rust toolchain.

    Args:
        rust_dir: Root directory of the consolidated Rust toolchain
        flag_file: Path to write the version info (INSTALLED_VERSION)
        archs: List of successfully processed architectures

    Writes:
        Either the rustc version string, or a fallback message listing
        which architectures were processed if rustc isn't executable.
    """
    rustc_path = rust_dir / "bin" / "rustc"
    version_info = f'rustc not installed (processed: {", ".join(archs)})\n'

    if rustc_path.exists():
        try:
            result = subprocess.run(
                [str(rustc_path), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                version_info = result.stdout
            else:
                get_logger().warning("rustc --version failed: %s", result.stderr)
        except Exception as e:
            get_logger().warning("Failed to execute rustc: %s", e)

    flag_file.write_text(version_info, encoding=ENCODING)
    get_logger().info("Rust version: %s", version_info.strip())


def setup_rust_toolchain(source_tree: Path, ci_mode: bool = False) -> Path:
    """
    Set up Rust toolchain with multi-architecture cross-compilation support.

    This is the main entry point for Rust toolchain setup. It consolidates
    multiple architecture-specific Rust distributions into a unified toolchain
    layout suitable for cross-compiling Windows Chromium.

    Args:
        source_tree: Path to the Chromium source tree root
                     (expects third_party/rust-toolchain-{x64,x86,arm}/)
        ci_mode: If True, skip setup if INSTALLED_VERSION file exists
                 (optimization for CI/caching systems)

    Returns:
        Path to the consolidated rust-toolchain directory

    Raises:
        SystemExit: If no architectures can be processed successfully
    """
    # Detect host architecture: Python's sys.maxsize reveals pointer size
    host_cpu_is_64_bit = sys.maxsize > 2**32

    third_party = source_tree / "third_party"
    rust_dir_dst = third_party / "rust-toolchain"
    rust_flag_file = rust_dir_dst / "INSTALLED_VERSION"

    # CI mode optimization: Skip setup if already completed
    # The INSTALLED_VERSION file acts as a stamp for CI caching
    if ci_mode and rust_flag_file.exists():
        return rust_dir_dst

    get_logger().info("Setting up Rust toolchain with multi-architecture support...")

    # Architecture configuration: Maps architecture names to their source directories
    # and target characteristics. The host architecture gets special treatment (top-level
    # installation + symlinks), while target architectures get full copies in subdirs.
    arch_configs = {
        "x86_64": {
            "source": third_party
            / "rust-toolchain-x64",  # Downloaded from downloads.ini
            "target_subdir": "x86_64",  # Subdirectory name in consolidated layout
            "is_host": host_cpu_is_64_bit,  # True if this is the build machine's arch
            "rust_target": "x86_64-unknown-linux-gnu",  # Rust target triple
        },
        "i686": {
            "source": third_party / "rust-toolchain-x86",
            "target_subdir": "i686",
            "is_host": not host_cpu_is_64_bit,
            "rust_target": "i686-unknown-linux-gnu",
        },
        "aarch64": {
            "source": third_party / "rust-toolchain-arm",
            "target_subdir": "aarch64",
            "is_host": False,  # ARM64 is never the host for this build setup
            "rust_target": "aarch64-unknown-linux-gnu",
        },
    }

    # Determine which architecture is the host (only one should have is_host=True)
    host_arch = next(
        (arch for arch, cfg in arch_configs.items() if cfg["is_host"]), None
    )
    if not host_arch:
        get_logger().error("Unable to determine host architecture")
        sys.exit(1)

    get_logger().info("Host architecture: %s", host_arch)

    # Create the destination directory structure
    rust_dir_dst.mkdir(parents=True, exist_ok=True)
    (rust_dir_dst / "bin").mkdir(exist_ok=True)
    (rust_dir_dst / "lib").mkdir(exist_ok=True)

    # Track which architectures were successfully processed for diagnostics
    successful_archs = []

    # Process each architecture: merge its components into the consolidated layout
    for arch, config in arch_configs.items():
        src_root = config["source"]
        target_subdir = config["target_subdir"]
        rust_target = config["rust_target"]
        is_host = config["is_host"]

        # Skip this architecture if its source directory doesn't exist
        # (e.g., if downloads.ini only includes some architectures)
        if not src_root.exists():
            get_logger().warning(
                "Source directory not found: %s, skipping %s", src_root, arch
            )
            continue

        get_logger().info("Processing %s architecture...", arch)

        # Determine installation targets for this architecture
        # Host: Install to top-level (rust_dir_dst)
        # Target: Install to architecture-specific subdirectory
        install_targets = []
        if is_host:
            install_targets.append(rust_dir_dst)
        else:
            arch_dir = rust_dir_dst / target_subdir
            arch_dir.mkdir(parents=True, exist_ok=True)
            install_targets.append(arch_dir)

        # Track which components are successfully installed
        components_found = []

        # Install each component from COMPONENTS_CONFIG
        for comp in COMPONENTS_CONFIG:
            # Replace {target} placeholder with actual target triple
            # e.g., "rust-std-{target}" → "rust-std-x86_64-unknown-linux-gnu"
            comp_dir_name = comp["name"].format(target=rust_target)
            comp_src_path = src_root / comp_dir_name

            # Check if this component exists in the source distribution
            if not comp_src_path.exists():
                if comp["required"]:
                    get_logger().warning(
                        "Required component %s not found in %s", comp_dir_name, src_root
                    )
                continue

            components_found.append(comp_dir_name)

            # Merge bin/ and lib/ subdirectories if they exist for this component
            for sub in ["bin", "lib"]:
                # Skip subdirectories that this component doesn't provide
                if sub == "bin" and not comp["has_bin"]:
                    continue
                if sub == "lib" and not comp["has_lib"]:
                    continue

                sub_src = comp_src_path / sub
                if not sub_src.exists():
                    continue

                # Merge into all installation targets (usually just one)
                for install_root in install_targets:
                    sub_dst = install_root / sub
                    get_logger().debug("Merging %s -> %s", sub_src, sub_dst)
                    _merge_tree(sub_src, sub_dst)

        get_logger().info(
            "Installed components for %s: %s", arch, ", ".join(components_found)
        )

        # Special handling for host architecture
        if is_host:
            # Fix shared libraries that may have been overwritten by wrong architecture
            # This must happen after all components are merged
            _fix_top_level_libs(rust_dir_dst / "lib", arch)

            # Create a subdirectory for the host architecture with symlinks
            # This provides a consistent interface: all architectures have a
            # subdirectory, and the host subdirectory just symlinks to top-level
            host_subdir = rust_dir_dst / target_subdir
            host_subdir.mkdir(parents=True, exist_ok=True)

            for sub in ["bin", "lib"]:
                link_path = host_subdir / sub
                target_path = Path("..") / sub  # Relative symlink: ../bin or ../lib

                # Remove existing directory/symlink if present
                if link_path.exists() or link_path.is_symlink():
                    if link_path.is_dir() and not link_path.is_symlink():
                        shutil.rmtree(link_path)
                    else:
                        link_path.unlink()

                # Create relative symlink for portability
                link_path.symlink_to(target_path)
                get_logger().info(
                    "Created host symlink: %s -> %s", link_path, target_path
                )

        successful_archs.append(arch)

    # Verify at least one architecture was successfully processed
    # If all architectures failed, the build cannot continue
    if not successful_archs:
        get_logger().error("Failed to process any architecture.")
        sys.exit(1)

    # Install Windows target standard libraries for cross-compilation
    get_logger().info("Installing Windows target standard libraries...")
    windows_std_configs = {
        "x86_64-pc-windows-msvc": third_party / "rust-std-windows-x64",
        "i686-pc-windows-msvc": third_party / "rust-std-windows-x86",
        "aarch64-pc-windows-msvc": third_party / "rust-std-windows-arm",
    }

    for target_triple, src_dir in windows_std_configs.items():
        if not src_dir.exists():
            get_logger().warning(
                "Windows std source not found: %s (skipping %s)",
                src_dir,
                target_triple,
            )
            continue

        # The std component directory structure is: rust-std-{target}/lib/
        std_comp_dir = src_dir / f"rust-std-{target_triple}"
        if not std_comp_dir.exists():
            get_logger().warning(
                "Expected component directory not found: %s", std_comp_dir
            )
            continue

        std_lib_src = std_comp_dir / "lib"
        if std_lib_src.exists():
            std_lib_dst = rust_dir_dst / "lib"
            get_logger().info(
                "Merging Windows std for %s: %s -> %s",
                target_triple,
                std_lib_src,
                std_lib_dst,
            )
            _merge_tree(std_lib_src, std_lib_dst)
        else:
            get_logger().warning("lib directory not found in %s", std_comp_dir)

    # Generate version file for CI caching and diagnostics
    _generate_version_file(rust_dir_dst, rust_flag_file, successful_archs)

    get_logger().info("Rust toolchain setup completed")
    return rust_dir_dst
