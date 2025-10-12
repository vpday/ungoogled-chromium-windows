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
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as list_file:
            list_file_path = list_file.name
            for file_path in file_list:
                list_file.write(str(file_path).replace('\\', '/') + '\n')

        try:
            cmd = [
                '7z', 'a', '-t7z', '-mx=9', '-mtc=on',
                str(output_path.resolve()),
                f'@{list_file_path}'
            ]

            result = subprocess.run(
                cmd,
                cwd=str(build_outputs),
                capture_output=True,
                text=True,
                check=True
            )

        finally:
            try:
                os.unlink(list_file_path)
            except Exception:
                pass

    except Exception as e:
        get_logger().error('7z archive creation failed: %s', e)

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
