#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 The ungoogled-chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
Rust toolchain management for ungoogled-chromium Windows cross-compilation.

Sets up a Linux x86_64 host Rust toolchain with the target Windows standard library.
"""

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parent / "ungoogled-chromium" / "utils")
)
from _common import ENCODING, get_logger

sys.path.pop(0)

from windows_target import WindowsTarget


def _generate_version_file(rust_dir: Path, flag_file: Path) -> None:
    """Generate a version file to track the installed Rust toolchain."""
    rustc_path = rust_dir / "bin" / "rustc"
    version_info = "rustc not installed\n"

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


def setup_rust_toolchain(
        source_tree: Path,
        target: WindowsTarget,
        ci_mode: bool = False,
) -> Path:
    """
    Set up Rust toolchain for Windows cross-compilation.

    Deploys a single Linux x86_64 host rustc/cargo toolchain with the matching
    Windows rust-std target library, and links LLVM libclang for bindgen.

    Args:
        source_tree: Path to the Chromium source tree root
        target: Resolved Windows build target
        ci_mode: If True, skip setup if INSTALLED_VERSION file exists

    Returns:
        Path to the consolidated rust-toolchain directory
    """
    third_party = source_tree / "third_party"
    rust_dir_dst = third_party / "rust-toolchain"
    rust_flag_file = rust_dir_dst / "INSTALLED_VERSION"

    if ci_mode and rust_flag_file.exists():
        return rust_dir_dst

    get_logger().info("Setting up Rust toolchain...")

    host_toolchain_src = third_party / "rust-toolchain-x64"
    if not host_toolchain_src.exists():
        get_logger().error("Host Rust toolchain not found at %s", host_toolchain_src)
        sys.exit(1)

    rust_dir_dst.mkdir(parents=True, exist_ok=True)
    dst_bin = rust_dir_dst / "bin"
    dst_lib = rust_dir_dst / "lib"
    dst_bin.mkdir(exist_ok=True)
    dst_lib.mkdir(exist_ok=True)

    # Copy host components (rustc, cargo, rustfmt, rust-std for x86_64-unknown-linux-gnu)
    host_components = [
        "rustc",
        "cargo",
        "rustfmt-preview",
        "rust-std-x86_64-unknown-linux-gnu",
    ]
    for comp in host_components:
        comp_dir = host_toolchain_src / comp
        if not comp_dir.exists():
            get_logger().warning("Component %s not found in %s", comp, host_toolchain_src)
            continue
        comp_bin = comp_dir / "bin"
        if comp_bin.exists():
            shutil.copytree(comp_bin, dst_bin, dirs_exist_ok=True, symlinks=True)
        comp_lib = comp_dir / "lib"
        if comp_lib.exists():
            shutil.copytree(comp_lib, dst_lib, dirs_exist_ok=True, symlinks=True)

    # Deploy target Windows standard library
    target_std_dir = (third_party / target.windows_rust_std_selector / f"rust-std-{target.windows_rust_target}" / "lib")
    if target_std_dir.exists():
        get_logger().info("Deploying Windows std for %s: %s -> %s", target.windows_rust_target, target_std_dir, dst_lib)
        shutil.copytree(target_std_dir, dst_lib, dirs_exist_ok=True, symlinks=True)
    else:
        get_logger().warning("Windows std source not found at %s", target_std_dir)

    # Provide libclang shared libraries in rust-toolchain/lib for bindgen
    llvm_lib_dir = third_party / "llvm-build" / "Release+Asserts" / "lib"
    if llvm_lib_dir.exists():
        for item in llvm_lib_dir.glob("libclang.so*"):
            dst_link = dst_lib / item.name
            if dst_link.is_symlink() or dst_link.exists():
                if dst_link.is_dir() and not dst_link.is_symlink():
                    shutil.rmtree(dst_link)
                else:
                    dst_link.unlink()
            try:
                dst_link.symlink_to(item)
            except OSError:
                shutil.copy2(item, dst_link)

    # Generate version stamp
    _generate_version_file(rust_dir_dst, rust_flag_file)

    get_logger().info("Rust toolchain setup completed")
    return rust_dir_dst
