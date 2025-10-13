#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 The ungoogled-chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
ungoogled-chromium packaging script for Microsoft Windows
"""

import sys
if sys.version_info.major < 3:
    raise RuntimeError('Python 3 is required for this script.')

import argparse
import os
import platform
from pathlib import Path
import shutil
import subprocess
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent / 'ungoogled-chromium' / 'utils'))
import filescfg
from _common import ENCODING, get_chromium_version, get_logger
sys.path.pop(0)

def _get_release_revision():
    revision_path = Path(__file__).resolve().parent / 'ungoogled-chromium' / 'revision.txt'
    return revision_path.read_text(encoding=ENCODING).strip()

def _get_packaging_revision():
    revision_path = Path(__file__).resolve().parent / 'revision.txt'
    return revision_path.read_text(encoding=ENCODING).strip()

_cached_target_cpu = None

def _get_target_cpu(build_outputs):
    global _cached_target_cpu
    if not _cached_target_cpu:
        with open(build_outputs / 'args.gn', 'r') as f:
            args_gn_text = f.read()
            for cpu in ('x64', 'x86', 'arm64'):
                if f'target_cpu="{cpu}"' in args_gn_text:
                    _cached_target_cpu = cpu
                    break
    assert _cached_target_cpu
    return _cached_target_cpu

def _create_7z_archive(file_list, build_outputs, output_path):
    """
    Create a 7z archive from the file list.

    Args:
        file_list: List of Path objects relative to build_outputs
        build_outputs: Base directory containing the files
        output_path: Output path for the 7z archive
    """
    # Extract root folder name from output filename
    archive_root = output_path.stem

    temp_work_dir = None

    try:
        # Create temporary work directory in same location as build outputs
        # This ensures hard links work (must be on same volume)
        temp_work_dir = tempfile.mkdtemp(prefix=f'{archive_root}_tmp_', dir='build')
        archive_root_dir = Path(temp_work_dir) / archive_root

        # Create directory structure and hard links for files
        for file_path in file_list:
            source_path = build_outputs / file_path
            dest_path = archive_root_dir / file_path

            if source_path.is_dir():
                # Create directory in temp structure
                dest_path.mkdir(parents=True, exist_ok=True)
                # Recursively link all files in directory
                for sub_path in source_path.rglob('*'):
                    if sub_path.is_file():
                        dest_sub = dest_path / sub_path.relative_to(source_path)
                        dest_sub.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            os.link(sub_path, dest_sub)
                        except OSError:
                            shutil.copy2(sub_path, dest_sub)
            else:
                # Create parent directories
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                # Create hard link to file (doesn't use extra disk space)
                try:
                    os.link(source_path, dest_path)
                except OSError:
                    shutil.copy2(source_path, dest_path)

        cmd = [
            '7z', 'a', '-t7z', '-mx=9', '-mtc=on',
            str(output_path.resolve()),
            archive_root
        ]

        result = subprocess.run(
            cmd,
            cwd=temp_work_dir,
            capture_output=True,
            text=True,
            check=True
        )

    except Exception as e:
        get_logger().error('7z archive creation failed: %s', e)
    finally:
        # Cleanup: Remove entire temporary directory
        # Safe because we used hard links (deleting link doesn't affect source)
        if temp_work_dir and Path(temp_work_dir).exists():
            try:
                shutil.rmtree(temp_work_dir, ignore_errors=True)
            except Exception as e:
                get_logger().error('Failed to remove temp directory: %s', e)

def main():
    """Entrypoint"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--cpu-arch',
        metavar='ARCH',
        default=platform.architecture()[0],
        choices=('64bit', '32bit'),
        help=('Filter build outputs by a target CPU. '
              'This is the same as the "arch" key in FILES.cfg. '
              'Default (from platform.architecture()): %(default)s'))
    args = parser.parse_args()

    build_outputs = Path('build/src/out/Default')

    shutil.copyfile('build/src/out/Default/mini_installer.exe',
        'build/ungoogled-chromium_{}-{}.{}_installer_{}.exe'.format(
            get_chromium_version(), _get_release_revision(),
            _get_packaging_revision(), _get_target_cpu(build_outputs)))

    timestamp = None
    try:
        with open('build/src/build/util/LASTCHANGE.committime', 'r') as ct:
            timestamp = int(ct.read())
    except FileNotFoundError:
        pass

    output = Path('build/ungoogled-chromium_{}-{}.{}_windows_{}.zip'.format(
        get_chromium_version(), _get_release_revision(),
        _get_packaging_revision(), _get_target_cpu(build_outputs)))

    excluded_files = set([
        Path('mini_installer.exe'),
        Path('mini_installer_exe_version.rc'),
        Path('setup.exe'),
        Path('chrome.packed.7z'),
    ])
    files_generator = filescfg.filescfg_generator(
        Path('build/src/chrome/tools/build/win/FILES.cfg'),
        build_outputs, args.cpu_arch, excluded_files)

    file_list = list(files_generator)

    filescfg.create_archive(
        iter(file_list), tuple(), build_outputs, output, timestamp)

    output_7z = Path('build/ungoogled-chromium_{}-{}.{}_windows_{}.7z'.format(
        get_chromium_version(), _get_release_revision(),
        _get_packaging_revision(), _get_target_cpu(build_outputs)))

    _create_7z_archive(file_list, build_outputs, output_7z)

if __name__ == '__main__':
    main()
