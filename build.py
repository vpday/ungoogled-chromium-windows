#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 The ungoogled-chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
ungoogled-chromium build script for Linux
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from build_common import (
    run_build_process,
    run_build_process_timeout,
    get_target_arch_from_args,
    get_host_arch,
    should_skip_step,
    mark_step_complete,
)
from setup_rust import setup_rust_toolchain
from setup_utils import fix_tool_downloading, setup_toolchain
from setup_win_toolchain import setup_windows_toolchain

sys.path.insert(0, str(Path(__file__).resolve().parent / 'ungoogled-chromium' / 'utils'))
import downloads
import domain_substitution
import prune_binaries
import patches
from _common import ENCODING, USE_REGISTRY, ExtractorEnum, get_logger
sys.path.pop(0)

_ROOT_DIR = Path(__file__).resolve().parent
_PATCH_BIN_RELPATH = Path('/usr/bin/patch')


def main():
    """CLI Entrypoint"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--disable-ssl-verification',
        action='store_true',
        help='Disables SSL verification for downloading')
    parser.add_argument(
        '--7z-path',
        dest='sevenz_path',
        default=USE_REGISTRY,
        help=('Command or path to 7-Zip\'s "7z" binary. If "_use_registry" is '
              'specified, determine the path from the registry. Default: %(default)s'))
    parser.add_argument(
        '-j',
        type=int,
        dest='thread_count',
        help=('Number of CPU threads to use for compiling'))
    parser.add_argument(
        '--ci',
        action='store_true'
    )
    parser.add_argument(
        '--x86',
        action='store_true'
    )
    parser.add_argument(
        '--arm',
        action='store_true'
    )
    parser.add_argument(
        '--tarball',
        action='store_true'
    )
    args = parser.parse_args()

    # Set common variables
    source_tree = _ROOT_DIR / 'build' / 'src'
    downloads_cache = _ROOT_DIR / 'build' / 'download_cache'

    # Setup environment
    source_tree.mkdir(parents=True, exist_ok=True)
    downloads_cache.mkdir(parents=True, exist_ok=True)

    # Extractors
    extractors = {
        ExtractorEnum.SEVENZIP: args.sevenz_path,
    }

    # Prepare source folder
    if args.tarball:
        # Download chromium tarball
        download_info = downloads.DownloadInfo([_ROOT_DIR / 'ungoogled-chromium' / 'downloads.ini'])
        if should_skip_step(source_tree, '.download_chromium_tarball.stamp', args.ci):
            get_logger().info('Skipping chromium tarball download (already completed)')
        else:
            get_logger().info('Downloading chromium tarball...')
            downloads.retrieve_downloads(download_info, downloads_cache, None, True, args.disable_ssl_verification)
            try:
                downloads.check_downloads(download_info, downloads_cache, None)
            except downloads.HashMismatchError as exc:
                get_logger().error('File checksum does not match: %s', exc)
                exit(1)
            mark_step_complete(source_tree, '.download_chromium_tarball.stamp')
            get_logger().info('Chromium tarball download completed')

        # Unpack chromium tarball
        if should_skip_step(source_tree, '.unpack_chromium_tarball.stamp', args.ci):
            get_logger().info('Skipping chromium tarball unpacking (already completed)')
        else:
            get_logger().info('Unpacking chromium tarball...')
            downloads.unpack_downloads(download_info, downloads_cache, None, source_tree, extractors)
            mark_step_complete(source_tree, '.unpack_chromium_tarball.stamp')
            get_logger().info('Chromium tarball unpacking completed')
    else:
        # Clone sources
        if should_skip_step(source_tree, '.clone_chromium_sources.stamp', args.ci):
            get_logger().info('Skipping chromium source cloning (already completed)')
        else:
            get_logger().info('Clone sources...')

            # Determine sysroot and platform architecture for cross-compilation
            host_arch = get_host_arch()  # Linux build machine architecture
            target_arch = get_target_arch_from_args()  # Windows target architecture
            arch_mapping = {'x64': 'amd64', 'x86': 'i386', 'arm64': 'arm64'}
            platform_mapping = {'x64': 'win64', 'x86': 'win32', 'arm64': 'win-arm64'}
            sysroot_arch = arch_mapping[host_arch]  # Linux sysroot for build tools
            platform_str = platform_mapping[target_arch]  # Windows platform target

            run_build_process(
                sys.executable,
                str(Path('ungoogled-chromium', 'utils', 'clone.py')),
                '-o', 'build/src',
                '-p', platform_str,
                '-s', sysroot_arch
            )
            mark_step_complete(source_tree, '.clone_chromium_sources.stamp')

    # Retrieve windows downloads
    if should_skip_step(source_tree, '.download_windows_dependencies.stamp', args.ci):
        get_logger().info('Skipping Windows dependencies download (already completed)')
    else:
        get_logger().info('Downloading required files...')
        download_info_win = downloads.DownloadInfo([_ROOT_DIR / 'downloads.ini'])
        downloads.retrieve_downloads(download_info_win, downloads_cache, None, True, args.disable_ssl_verification)
        try:
            downloads.check_downloads(download_info_win, downloads_cache, None)
        except downloads.HashMismatchError as exc:
            get_logger().error('File checksum does not match: %s', exc)
            exit(1)
        mark_step_complete(source_tree, '.download_windows_dependencies.stamp')

    # Prune binaries
    if should_skip_step(source_tree, '.prune_binaries.stamp', args.ci):
        get_logger().info('Skipping binary pruning (already completed)')
    else:
        pruning_list = (_ROOT_DIR / 'ungoogled-chromium' / 'pruning.list') if args.tarball else (
                _ROOT_DIR / 'pruning.list')
        unremovable_files = prune_binaries.prune_files(
            source_tree,
            pruning_list.read_text(encoding=ENCODING).splitlines()
        )
        if unremovable_files:
            get_logger().error('Files could not be pruned: %s', unremovable_files)
            parser.exit(1)
        mark_step_complete(source_tree, '.prune_binaries.stamp')

    # Unpack downloads
    if should_skip_step(source_tree, '.unpack_windows_downloads.stamp', args.ci):
        get_logger().info('Skipping Windows downloads unpacking (already completed)')
    else:
        directx = source_tree / 'third_party' / 'microsoft_dxheaders' / 'src'
        if directx.exists():
            shutil.rmtree(directx)
            directx.mkdir()
        get_logger().info('Unpacking downloads...')
        download_info_win = downloads.DownloadInfo([_ROOT_DIR / 'downloads.ini'])
        downloads.unpack_downloads(download_info_win, downloads_cache, None, source_tree, extractors)
        mark_step_complete(source_tree, '.unpack_windows_downloads.stamp')

    # Move all contents from the LLVM-*-Linux-X64 folder to the Release+Asserts directory.
    if should_skip_step(source_tree, '.flatten_llvm_directory.stamp', args.ci):
        get_logger().info('Skipping LLVM directory flattening (already completed)')
    else:
        llvm_release_root = source_tree / 'third_party' / 'llvm-build' / 'Release+Asserts'
        if llvm_release_root.exists():
            versioned_dirs = list(llvm_release_root.glob('LLVM-*-Linux-X64'))
            if versioned_dirs:
                src_dir = versioned_dirs[0]
                get_logger().info('Flattening LLVM directory: %s -> %s', src_dir.name, llvm_release_root.name)

                for item in src_dir.iterdir():
                    dest_item = llvm_release_root / item.name
                    if dest_item.is_dir() and dest_item.exists():
                        shutil.rmtree(dest_item)
                    elif dest_item.is_file() and dest_item.exists():
                        dest_item.unlink()

                    shutil.move(str(item), str(llvm_release_root))

                if src_dir.exists():
                    shutil.rmtree(src_dir)
            else:
                get_logger().warning('No versioned LLVM directory found to flatten in %s', llvm_release_root)
        mark_step_complete(source_tree, '.flatten_llvm_directory.stamp')

    # Apply patches
    if should_skip_step(source_tree, '.apply_patches.stamp', args.ci):
        get_logger().info('Skipping patch application (already completed)')
    else:
        # First, ungoogled-chromium-patches
        get_logger().info('Applying ungoogled-chromium patches...')
        patches.apply_patches(
            patches.generate_patches_from_series(_ROOT_DIR / 'ungoogled-chromium' / 'patches', resolve=True),
            source_tree,
            patch_bin_path=(source_tree / _PATCH_BIN_RELPATH)
        )
        # Then Windows-specific patches
        get_logger().info('Applying Windows-specific patches...')
        patches.apply_patches(
            patches.generate_patches_from_series(_ROOT_DIR / 'patches', resolve=True),
            source_tree,
            patch_bin_path=(source_tree / _PATCH_BIN_RELPATH)
        )
        mark_step_complete(source_tree, '.apply_patches.stamp')

    # Substitute domains
    if should_skip_step(source_tree, '.apply_domain_substitution.stamp', args.ci):
        get_logger().info('Skipping domain substitution (already completed)')
    else:
        domain_substitution_list = (
                _ROOT_DIR / 'ungoogled-chromium' / 'domain_substitution.list') if args.tarball else (
                _ROOT_DIR / 'domain_substitution.list')
        domain_substitution.apply_substitution(
            _ROOT_DIR / 'ungoogled-chromium' / 'domain_regex.list',
            domain_substitution_list,
            source_tree,
            None
        )
        mark_step_complete(source_tree, '.apply_domain_substitution.stamp')

    # Set up Rust toolchain
    rust_dir_dst = setup_rust_toolchain(source_tree, ci_mode=args.ci)
    rust_lib_path = str(rust_dir_dst / 'lib')

    current_ld_path = os.environ.get('LD_LIBRARY_PATH', '')
    os.environ['LD_LIBRARY_PATH'] = f"{rust_lib_path}:{current_ld_path}" if current_ld_path else rust_lib_path

    # Output args.gn
    if should_skip_step(source_tree, '.write_gn_args.stamp', args.ci):
        get_logger().info('Skipping GN args generation (already completed)')
    else:
        (source_tree / 'out/Default').mkdir(parents=True, exist_ok=True)
        gn_flags = (_ROOT_DIR / 'ungoogled-chromium' / 'flags.gn').read_text(encoding=ENCODING)
        gn_flags += '\n'
        windows_flags = (_ROOT_DIR / 'flags.windows.gn').read_text(encoding=ENCODING)
        if args.x86:
            windows_flags = windows_flags.replace('x64', 'x86')
        elif args.arm:
            windows_flags = windows_flags.replace('x64', 'arm64')
        if args.tarball:
            windows_flags += '\nchrome_pgo_phase=0\n'
        gn_flags += windows_flags
        (source_tree / 'out/Default/args.gn').write_text(gn_flags, encoding=ENCODING)
        mark_step_complete(source_tree, '.write_gn_args.stamp')

    # Configure Windows Toolchain environment
    setup_windows_toolchain(source_tree, ci_mode=args.ci)

    clang_bin = source_tree / 'third_party' / 'llvm-build' / 'Release+Asserts' / 'bin'
    clang_bin_str = str(clang_bin)
    llvm_base = clang_bin.parent
    llvm_lib = str(llvm_base / 'lib')
    llvm_lib_x64 = llvm_lib + '/x86_64-unknown-linux-gnu'

    current_ld = os.environ.get('LD_LIBRARY_PATH', '')
    new_ld_paths = [str(llvm_lib), str(llvm_lib_x64)]
    if current_ld:
        new_ld_paths.append(current_ld)
    os.environ['LD_LIBRARY_PATH'] = os.pathsep.join(new_ld_paths)

    os.environ['CC'] = str(clang_bin / 'clang')
    os.environ['CXX'] = str(clang_bin / 'clang++')
    os.environ['AR'] = str(clang_bin / 'llvm-ar')
    os.environ['NM'] = str(clang_bin / 'llvm-nm')
    os.environ['LD'] = str(clang_bin / 'llvm-link')
    os.environ['LLVM_BIN'] = clang_bin_str
    os.environ['LLVM_BASE'] = str(llvm_base)
    os.environ['CXXFLAGS'] = f"-I{llvm_base}/include/c++/v1 -stdlib=libc++"
    os.environ['LDFLAGS'] = (
        f"-L{llvm_base}/lib "
        f"-L{llvm_lib_x64} "
        f"-stdlib=libc++ "
        f"-Wl,-rpath,{llvm_base}/lib "
        f"-Wl,-rpath,{llvm_lib_x64} "
        f"-Wl,--whole-archive -lc++abi -Wl,--no-whole-archive "
        f"-lpthread -ldl"
    )

    ninja_dir = source_tree / 'third_party' / 'ninja'
    os.environ['PATH'] = f"{os.environ.get('PATH', '')}:{ninja_dir}:{clang_bin_str}"
    os.environ['NINJA_STATUS'] = '[%p/%f/%t/%w] '

    if should_skip_step(source_tree, '.setup_toolchain.stamp', args.ci):
        get_logger().info('Skipping toolchain setup (already completed)')
    else:
        fix_tool_downloading(source_tree)
        setup_toolchain(source_tree, ci_mode=args.ci)
        mark_step_complete(source_tree, '.setup_toolchain.stamp')

    resource_dir = subprocess.check_output(
        [os.environ['CC'], '--print-resource-dir'],
        encoding=ENCODING
    ).strip()

    flags_to_append = f' -resource-dir={resource_dir} -B{clang_bin_str}'
    for flag_name in ('CXXFLAGS', 'CPPFLAGS', 'CFLAGS'):
        current_flags = os.environ.get(flag_name, '')
        os.environ[flag_name] = current_flags + flags_to_append

    # Enter source tree to run build commands
    os.chdir(source_tree)

    # Run GN bootstrap
    if should_skip_step(source_tree, '.gn_bootstrap.stamp', args.ci):
        get_logger().info('Skipping GN bootstrap (already completed)')
    else:
        run_build_process(
            sys.executable, 'tools/gn/bootstrap/bootstrap.py', '-o', 'out/Default/gn',
            '--skip-generate-buildfiles')
        mark_step_complete(source_tree, '.gn_bootstrap.stamp')

    # Run gn gen
    if should_skip_step(source_tree, '.gn_gen.stamp', args.ci):
        get_logger().info('Skipping GN gen (already completed)')
    else:
        run_build_process('out/Default/gn', 'gen', 'out/Default', '--fail-on-unused-args')
        mark_step_complete(source_tree, '.gn_gen.stamp')

    # Ninja commandline
    ninja_commandline = ['third_party/ninja/ninja']
    if args.thread_count is not None:
        ninja_commandline.append('-j')
        ninja_commandline.append(args.thread_count)
    ninja_commandline.append('-C')
    ninja_commandline.append('out/Default')
    ninja_commandline.append('chrome')
    ninja_commandline.append('chromedriver')
    ninja_commandline.append('mini_installer')

    # Run ninja
    if args.ci:
        run_build_process_timeout(*ninja_commandline, timeout=3.5 * 60 * 60)
        # package
        os.chdir(_ROOT_DIR)
        subprocess.run([sys.executable, 'package.py'])
    else:
        run_build_process(*ninja_commandline)


if __name__ == '__main__':
    main()
