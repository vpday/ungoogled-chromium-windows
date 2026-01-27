#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 The ungoogled-chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
Common build utilities for ungoogled-chromium Windows build.

This module provides foundational build utilities including:
- Process execution with timeout support
- Host and target architecture detection
"""

import os
import platform
import signal
import subprocess
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'ungoogled-chromium' / 'utils'))
from _common import ENCODING

sys.path.pop(0)


def run_build_process(*args, **kwargs):
    """
    Runs the subprocess with the correct environment variables for building
    """
    subprocess.run(args, check=True, encoding=ENCODING, **kwargs)


def run_build_process_timeout(*args, timeout):
    """
    Runs the subprocess with the correct environment variables for building
    """
    string_args = [str(a) for a in args]
    with subprocess.Popen(string_args, encoding=ENCODING, start_new_session=True) as proc:
        try:
            proc.wait(timeout)
            if proc.returncode != 0:
                raise RuntimeError('Build failed!')
        except subprocess.TimeoutExpired:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGINT)

            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
                proc.wait()

            raise KeyboardInterrupt


def get_host_arch():
    """
    Returns the normalized host architecture (x64, arm64, etc.)
    """
    machine = platform.machine().lower()
    if machine in ('amd64', 'x86_64'):
        return 'x64'
    elif machine == 'aarch64':
        return 'arm64'
    return machine


def get_target_arch_from_args():
    """
    Get target architecture from command line arguments.

    Returns:
        str: Target architecture ('x64', 'x86', or 'arm64')
    """
    if '--x86' in sys.argv:
        return 'x86'
    elif '--arm' in sys.argv:
        return 'arm64'
    return 'x64'


def get_stamp_path(source_tree, stamp_name):
    """
    Get path to stamp file for a build step.

    Args:
        source_tree: Path object of the source directory
        stamp_name: Name of the stamp file (e.g., '.download_chromium_tarball.stamp')

    Returns:
        Path: Full path to the stamp file
    """
    stamps_dir = source_tree / '.stamps'
    return stamps_dir / stamp_name


def should_skip_step(source_tree, stamp_name, ci_mode):
    """
    Check if a build step should be skipped based on stamp file existence.

    Args:
        source_tree: Path object of the source directory
        stamp_name: Name of the stamp file
        ci_mode: Boolean indicating if running in CI mode

    Returns:
        bool: True if step should be skipped, False otherwise
    """
    if not ci_mode:
        return False
    stamp_path = get_stamp_path(source_tree, stamp_name)
    return stamp_path.exists()


def mark_step_complete(source_tree, stamp_name):
    """
    Mark a build step as complete by creating stamp file.

    Args:
        source_tree: Path object of the source directory
        stamp_name: Name of the stamp file
    """
    stamp_path = get_stamp_path(source_tree, stamp_name)
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path.touch()
