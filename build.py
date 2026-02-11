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
    get_target_arch_from_args,
    get_host_arch,
    should_skip_step,
    mark_step_complete,
)
from setup_rust import setup_rust_toolchain
from setup_utils import (
    fix_tool_downloading,
    setup_toolchain,
    download_from_sha1,
    download_v8_builtins_pgo_profiles
)
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
    parser.add_argument(
        '--out-dir',
        type=Path,
        default=None,
        metavar='DIR',
        help='GN output directory. Default: build/src/out/Default'
    )
    args = parser.parse_args()

    # Set common variables
    source_tree = _ROOT_DIR / 'build' / 'src'
    downloads_cache = _ROOT_DIR / 'build' / 'download_cache'
    out_dir = (args.out_dir if args.out_dir else source_tree / 'out' / 'Default').resolve()

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

            # Initialize V8 git submodule
            if not (source_tree / "v8" / "BUILD.gn").exists():
                get_logger().info("Initializing v8 submodule...")
                run_build_process(
                    "git",
                    "submodule",
                    "update",
                    "--init",
                    "--depth=1",
                    "--progress",
                    "v8",
                    cwd=source_tree,
                )
                get_logger().info("v8 submodule initialized successfully")

            # Download V8 Builtins PGO profiles (V8-specific optimization data)
            get_logger().info("Downloading V8 Builtins PGO profiles...")
            download_v8_builtins_pgo_profiles(
                source_tree, args.disable_ssl_verification
            )

            mark_step_complete(source_tree, '.clone_chromium_sources.stamp')

    # Determine which Windows dependency components to download/unpack based on target architecture.
    target_arch = get_target_arch_from_args()
    win_components = [
        'llvm',
        'ninja',
        '7zip-linux',
        'nodejs',
        'esbuild',
        'directx-headers',
        'webauthn',
        'rust-x64',
        'rust-windows-create',
    ]
    # Select only the needed Rust toolchain packages.
    if target_arch == 'x64':
        win_components.append('rust-std-windows-x64')
    elif target_arch == 'x86':
        win_components.append('rust-std-windows-x86')
    elif target_arch == 'arm64':
        win_components.append('rust-std-windows-arm')

    # Retrieve windows downloads
    if should_skip_step(source_tree, '.download_windows_dependencies.stamp', args.ci):
        get_logger().info('Skipping Windows dependencies download (already completed)')
    else:
        get_logger().info('Downloading required files...')
        download_info_win = downloads.DownloadInfo([_ROOT_DIR / 'downloads.ini'])
        downloads.retrieve_downloads(download_info_win, downloads_cache, win_components, True, args.disable_ssl_verification)
        try:
            downloads.check_downloads(download_info_win, downloads_cache, win_components)
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
        downloads.unpack_downloads(download_info_win, downloads_cache, win_components, source_tree, extractors)
        mark_step_complete(source_tree, '.unpack_windows_downloads.stamp')

    # Setup 7z symlink (7za -> 7zz)
    if should_skip_step(source_tree, '.setup_7z_symlink.stamp', args.ci):
        get_logger().info('Skipping 7z symlink setup (already completed)')
    else:
        get_logger().info('Setting up 7z symlink for installer archive creation...')
        lzma_bin_dir = source_tree / 'third_party' / 'lzma_sdk' / 'bin' / 'host_platform'
        symlink_7za = lzma_bin_dir / '7za'
        target_7zz = lzma_bin_dir / '7zz'

        if target_7zz.exists():
            if symlink_7za.exists() or symlink_7za.is_symlink():
                symlink_7za.unlink()
            symlink_7za.symlink_to('7zz')
            get_logger().info('Created symlink: 7za -> 7zz')
        else:
            get_logger().warning('7zz binary not found at %s, skipping symlink creation', target_7zz)

        mark_step_complete(source_tree, '.setup_7z_symlink.stamp')

    # Apply patches
    if should_skip_step(source_tree, '.apply_patches.stamp', args.ci):
        get_logger().info('Skipping patch application (already completed)')
    else:
        # Prepare patches/series for x64 AVX2 optimizations
        series_file = _ROOT_DIR / 'patches' / 'series'
        avx2_patch_line = 'ungoogled-chromium/windows/windows-enable-avx2-optimizations.patch'

        # Determine if current build is x64
        is_x64 = not args.x86 and not args.arm

        # Read current series content
        series_content = series_file.read_text(encoding=ENCODING)
        series_lines = series_content.splitlines()

        # Check if AVX2 optimization patch is already in series
        has_avx2_patch = avx2_patch_line in series_lines

        # Verify patch file exists before modifying series
        avx2_patch_file = _ROOT_DIR / 'patches' / avx2_patch_line
        if not avx2_patch_file.exists():
            get_logger().warning('AVX2 optimization patch file not found: %s', avx2_patch_file)
        else:
            if is_x64 and not has_avx2_patch:
                # x64 build: add AVX2 optimizations patch
                series_lines.append(avx2_patch_line)
                new_content = '\n'.join(series_lines) + '\n'
                with series_file.open('w', encoding=ENCODING, newline='\n') as f:
                    f.write(new_content)
                get_logger().info('Added AVX2 optimization patch for x64 build')
            elif not is_x64 and has_avx2_patch:
                # Non-x64 build: remove AVX2 optimizations patch if present
                series_lines = [line for line in series_lines if line != avx2_patch_line]
                new_content = '\n'.join(series_lines) + '\n'
                with series_file.open('w', encoding=ENCODING, newline='\n') as f:
                    f.write(new_content)
                get_logger().info('Removed AVX2 optimization patch for non-x64 build')

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
        out_dir.mkdir(parents=True, exist_ok=True)
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
        (out_dir / 'args.gn').write_text(gn_flags, encoding=ENCODING)
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

    if should_skip_step(source_tree, '.setup_toolchain.stamp', args.ci):
        get_logger().info('Skipping toolchain setup (already completed)')
    else:
        fix_tool_downloading(source_tree)
        setup_toolchain(source_tree, ci_mode=args.ci)

        # Download rc binary for cross-compilation
        rc_sha1_file = source_tree / 'build/toolchain/win/rc/linux64/rc.sha1'
        rc_binary = source_tree / 'build/toolchain/win/rc/linux64/rc'
        if rc_sha1_file.exists() and not rc_binary.exists():
            get_logger().info('Downloading rc binary for Linux cross-compilation...')
            download_from_sha1(rc_sha1_file, rc_binary, 'chromium-browser-clang/rc')
            get_logger().info('rc binary downloaded successfully')
        elif rc_binary.exists():
            get_logger().info('rc binary already exists, skipping download')
        else:
            get_logger().warning('rc.sha1 file not found, skipping rc binary download')

        mark_step_complete(source_tree, '.setup_toolchain.stamp')

    resource_dir = subprocess.check_output(
        [os.environ['CC'], '--print-resource-dir'],
        encoding=ENCODING
    ).strip()

    flags_to_append = f' -resource-dir={resource_dir} -B{clang_bin_str}'
    for flag_name in ('CXXFLAGS', 'CPPFLAGS', 'CFLAGS'):
        current_flags = os.environ.get(flag_name, '')
        os.environ[flag_name] = current_flags + flags_to_append

    # When out_dir is outside source_tree (e.g. CI split-disk layout), GN-generated
    # scripts use relative paths like ../../third_party/... from the build dir.
    # Create a third_party symlink at out_dir/../.. so those paths resolve correctly.
    gn_parent = out_dir.parent.parent
    if gn_parent.resolve() != source_tree.resolve():
        third_party_link = gn_parent / 'third_party'
        if gn_parent.exists() and not third_party_link.exists():
            third_party_link.symlink_to(source_tree / 'third_party')

    # Enter source tree to run build commands
    os.chdir(source_tree)

    # Run GN bootstrap
    if should_skip_step(source_tree, '.gn_bootstrap.stamp', args.ci):
        get_logger().info('Skipping GN bootstrap (already completed)')
    else:
        run_build_process(
            sys.executable, 'tools/gn/bootstrap/bootstrap.py', '-o', str(out_dir / 'gn'),
            '--skip-generate-buildfiles')
        mark_step_complete(source_tree, '.gn_bootstrap.stamp')

    # Create buildtools/linux64/gn symlink for licenses.py GN discovery
    gn_binary = out_dir / 'gn'
    buildtools_gn = source_tree / 'buildtools' / 'linux64' / 'gn'
    if gn_binary.exists():
        buildtools_gn.parent.mkdir(parents=True, exist_ok=True)
        if not buildtools_gn.exists() or buildtools_gn.is_symlink():
            if buildtools_gn.is_symlink():
                buildtools_gn.unlink()
            buildtools_gn.symlink_to(gn_binary)

    # Run gn gen
    if should_skip_step(source_tree, '.gn_gen.stamp', args.ci):
        get_logger().info('Skipping GN gen (already completed)')
    else:
        run_build_process(str(out_dir / 'gn'), 'gen', str(out_dir), '--fail-on-unused-args')
        mark_step_complete(source_tree, '.gn_gen.stamp')

    # Ninja commandline
    ninja_commandline = ['third_party/ninja/ninja']
    if args.thread_count is not None:
        ninja_commandline.append('-j')
        ninja_commandline.append(args.thread_count)
    ninja_commandline.append('-C')
    ninja_commandline.append(str(out_dir))
    ninja_commandline.append('chrome')
    ninja_commandline.append('chromedriver')
    ninja_commandline.append('mini_installer')

    # Run ninja
    run_build_process(*ninja_commandline)

    # Package (CI mode only)
    if args.ci:
        os.chdir(_ROOT_DIR)
        subprocess.run([sys.executable, 'package.py', '--out-dir', str(out_dir)])


if __name__ == '__main__':
    main()
