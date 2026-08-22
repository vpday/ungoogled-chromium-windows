#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 The ungoogled-chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
ungoogled-chromium packaging script for Linux
"""

import sys

if sys.version_info.major < 3:
    raise RuntimeError('Python 3 is required for this script.')

import argparse
from pathlib import Path
import re
import shutil

_ROOT_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(Path(__file__).resolve().parent / 'ungoogled-chromium' / 'utils'))
import filescfg
from _common import ENCODING, get_chromium_version

sys.path.pop(0)

from windows_target import WindowsTarget, resolve_windows_target


def _get_release_revision():
    revision_path = Path(__file__).resolve().parent / 'ungoogled-chromium' / 'revision.txt'
    return revision_path.read_text(encoding=ENCODING).strip()


def _get_packaging_revision():
    revision_path = Path(__file__).resolve().parent / 'revision.txt'
    return revision_path.read_text(encoding=ENCODING).strip()


def read_build_target(build_outputs: Path) -> WindowsTarget:
    """Read the single canonical target_cpu assignment from args.gn."""
    args_gn_path = build_outputs / 'args.gn'
    assignments = [
        line for line in args_gn_path.read_text(encoding=ENCODING).splitlines()
        if re.match(r'^\s*target_cpu\b', line)
    ]
    if not assignments:
        raise RuntimeError(f'Missing target_cpu assignment in {args_gn_path}')
    if len(assignments) != 1:
        raise RuntimeError(
            f'Expected exactly one target_cpu assignment in {args_gn_path}; '
            f'found {len(assignments)}'
        )

    match = re.fullmatch(r'\s*target_cpu\s*=\s*"([^"]+)"\s*', assignments[0])
    if not match:
        raise RuntimeError(f'Malformed target_cpu assignment in {args_gn_path}')
    try:
        return resolve_windows_target(match.group(1))
    except ValueError as exc:
        raise RuntimeError(f'Unsupported target_cpu in {args_gn_path}: {match.group(1)!r}') from exc


def validate_package_filter(
        target: WindowsTarget,
        requested_filter: str | None,
) -> str:
    """Return the target filter after checking an optional compatibility assertion."""
    if requested_filter is not None and requested_filter != target.package_filter:
        raise RuntimeError(
            f'Package filter {requested_filter!r} does not match '
            f'args.gn target {target.id!r} ({target.package_filter!r})'
        )
    return target.package_filter


def main():
    """Entrypoint"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--cpu-arch',
        metavar='ARCH',
        default=None,
        choices=('64bit', '32bit', 'arm'),
        help=('Filter build outputs by a target CPU. '
              'This is the same as the "arch" key in FILES.cfg. '
              'When provided, it must match target_cpu in args.gn.'))
    parser.add_argument(
        '--out-dir',
        type=Path,
        default=None,
        metavar='DIR',
        help='Build output directory. Default: build/src/out/Default'
    )
    args = parser.parse_args()

    build_outputs = (args.out_dir if args.out_dir else _ROOT_DIR / 'build' / 'src' / 'out' / 'Default').resolve()
    target = read_build_target(build_outputs)
    package_filter = validate_package_filter(target, args.cpu_arch)

    shutil.copyfile(str(build_outputs / 'mini_installer.exe'),
                    'build/ungoogled-chromium_{}-{}.{}_installer_{}.exe'.format(
                        get_chromium_version(), _get_release_revision(),
                        _get_packaging_revision(), target.id))

    timestamp = None
    try:
        with open('build/src/build/util/LASTCHANGE.committime', 'r') as ct:
            timestamp = int(ct.read())
    except FileNotFoundError:
        pass

    output = Path('build/ungoogled-chromium_{}-{}.{}_windows_{}.zip'.format(
        get_chromium_version(), _get_release_revision(),
        _get_packaging_revision(), target.id))

    excluded_files = set([
        Path('mini_installer.exe'),
        Path('mini_installer_exe_version.rc'),
        Path('setup.exe'),
        Path('chrome.packed.7z'),
    ])
    files_generator = filescfg.filescfg_generator(
        Path('build/src/chrome/tools/build/win/FILES.cfg'),
        build_outputs, package_filter, excluded_files)
    filescfg.create_archive(
        files_generator, tuple(), build_outputs, output, timestamp)


if __name__ == '__main__':
    main()
