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
import re
import shutil
import subprocess
import sys
from pathlib import Path

from build_common import (
    build_step,
    run_build_process,
    get_host_arch,
)
from setup_rust import setup_rust_toolchain
from setup_utils import (
    fix_tool_downloading,
    setup_toolchain,
    download_from_sha1,
    download_v8_builtins_pgo_profiles
)
from setup_win_toolchain import setup_windows_toolchain
from windows_target import SUPPORTED_TARGET_IDS, WindowsTarget, resolve_windows_target

sys.path.insert(0, str(Path(__file__).resolve().parent / 'ungoogled-chromium' / 'utils'))
import downloads
import domain_substitution
import prune_binaries
import patches
from _common import ENCODING, USE_REGISTRY, ExtractorEnum, get_logger

sys.path.pop(0)

_ROOT_DIR = Path(__file__).resolve().parent
_PATCH_BIN_RELPATH = Path('/usr/bin/patch')

# Target-specific optimization patches
_OPTIMIZATION_PATCHES_BY_TARGET: dict[str, tuple[str, ...]] = {
    'x64': (
        'ungoogled-chromium/windows/windows-x86-optimizations.patch',
        'ungoogled-chromium/windows/windows-x64-optimizations.patch',
    ),
    'x86': (
        'ungoogled-chromium/windows/windows-x86-optimizations.patch',
    ),
    'arm64': (),
}


def _get_target_optimization_patches(target: WindowsTarget) -> tuple[str, ...]:
    """Return the ordered tuple of optimization patch paths for the given Windows target."""
    return _OPTIMIZATION_PATCHES_BY_TARGET.get(target.id, ())


def _resolve_windows_patches(target: WindowsTarget) -> list[Path]:
    """Return the resolved list of Windows patches, appending target-specific optimization patches."""
    base_patches = list(
        patches.generate_patches_from_series(_ROOT_DIR / 'patches', resolve=True)
    )
    target_relpaths = _get_target_optimization_patches(target)
    target_patches = [
        (_ROOT_DIR / 'patches' / relpath).resolve()
        for relpath in target_relpaths
    ]
    missing_patch_files = [p for p in target_patches if not p.exists()]
    if missing_patch_files:
        raise RuntimeError(
            'Optimization patch files not found: '
            + ', '.join(map(str, missing_patch_files))
        )
    return base_patches + target_patches


def _create_argument_parser():
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
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument(
        '--target',
        choices=SUPPORTED_TARGET_IDS
    )
    target_group.add_argument(
        '--x86',
        action='store_true'
    )
    target_group.add_argument(
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
    return parser


def _resolve_cli_target(args) -> WindowsTarget:
    target_id = args.target or ('x86' if args.x86 else 'arm64' if args.arm else 'x64')
    return resolve_windows_target(target_id)


def _get_windows_components(target: WindowsTarget):
    components = [
        'llvm',
        'ninja',
        '7zip-linux',
        'nodejs',
        'go-x64',
        'esbuild',
        'directx-headers',
        'webauthn',
        'rust-x64',
        'rust-windows-create',
        target.windows_rust_std_selector,
    ]
    if target.id != 'x64':
        components.append(target.rust_download_selector)
    if target.id == 'arm64':
        components.append('go-arm64')
    return components


def _set_gn_target_args(windows_flags: str, target: WindowsTarget):
    pattern = r'(?m)^(target_cpu\s*=\s*")[^"]*("\s*)$'
    updated_flags, replacement_count = re.subn(
        pattern,
        rf'\g<1>{target.gn_target_cpu}\g<2>',
        windows_flags,
    )
    if replacement_count != 1:
        raise RuntimeError(
            f"Expected exactly one target_cpu assignment in flags.windows.gn; found {replacement_count}"
        )
    return updated_flags


def _generate_gn_flags(target: WindowsTarget, is_tarball: bool) -> str:
    """Combine base and windows GN flags, adjusting for target architecture and build mode."""
    gn_flags = (_ROOT_DIR / 'ungoogled-chromium' / 'flags.gn').read_text(encoding=ENCODING)
    gn_flags += '\n'
    windows_flags = (_ROOT_DIR / 'flags.windows.gn').read_text(encoding=ENCODING)
    windows_flags = _set_gn_target_args(windows_flags, target)
    if is_tarball:
        windows_flags += '\nchrome_pgo_phase=0\n'
    gn_flags += windows_flags
    return gn_flags


def _compute_build_environment(source_tree: Path, target: WindowsTarget, rust_dir_dst: Path) -> dict:
    """Compute and apply compiler and toolchain environment variables."""
    clang_bin = source_tree / 'third_party' / 'llvm-build' / 'Release+Asserts' / 'bin'
    clang_bin_str = str(clang_bin)
    llvm_base = clang_bin.parent
    llvm_lib = str(llvm_base / 'lib')
    llvm_lib_x64 = llvm_lib + '/x86_64-unknown-linux-gnu'
    rust_lib_path = str(rust_dir_dst / 'lib')

    current_ld = os.environ.get('LD_LIBRARY_PATH', '')
    new_ld_paths = [rust_lib_path, str(llvm_lib), str(llvm_lib_x64)]
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

    resource_dir = subprocess.check_output(
        [os.environ['CC'], '--print-resource-dir'],
        encoding=ENCODING
    ).strip()

    flags_to_append = f' -resource-dir={resource_dir} -B{clang_bin_str}'
    for flag_name in ('CXXFLAGS', 'CPPFLAGS', 'CFLAGS'):
        current_flags = os.environ.get(flag_name, '')
        os.environ[flag_name] = current_flags + flags_to_append

    return os.environ


def _step_prepare_sources(
        source_tree: Path,
        downloads_cache: Path,
        target: WindowsTarget,
        is_tarball: bool,
        disable_ssl: bool,
        ci_mode: bool,
        extractors: dict,
) -> None:
    # Prepare source folder
    if is_tarball:
        # Download chromium tarball
        download_info = downloads.DownloadInfo([_ROOT_DIR / 'ungoogled-chromium' / 'downloads.ini'])
        with build_step(source_tree, '.download_chromium_tarball.stamp', 'downloading chromium tarball',
                        ci_mode) as should_run:
            if should_run:
                downloads.retrieve_downloads(download_info, downloads_cache, None, True, disable_ssl)
                try:
                    downloads.check_downloads(download_info, downloads_cache, None)
                except downloads.HashMismatchError as exc:
                    get_logger().error('File checksum does not match: %s', exc)
                    raise

        # Unpack chromium tarball
        with build_step(source_tree, '.unpack_chromium_tarball.stamp', 'unpacking chromium tarball',
                        ci_mode) as should_run:
            if should_run:
                downloads.unpack_downloads(download_info, downloads_cache, None, source_tree, extractors)
    else:
        # Clone sources
        with build_step(source_tree, '.clone_chromium_sources.stamp', 'cloning chromium sources',
                        ci_mode) as should_run:
            if should_run:
                # Determine sysroot and platform architecture for cross-compilation
                run_build_process(
                    sys.executable,
                    str(Path('ungoogled-chromium', 'utils', 'clone.py')),
                    '-o', 'build/src',
                    '-p', target.clone_platform,
                    '-s', 'amd64'
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
                download_v8_builtins_pgo_profiles(source_tree, disable_ssl)


def _step_download_windows_dependencies(
        source_tree: Path,
        downloads_cache: Path,
        target: WindowsTarget,
        disable_ssl: bool,
        ci_mode: bool,
) -> None:
    # Determine which Windows dependency components to download/unpack based on target architecture.
    win_components = _get_windows_components(target)

    # Retrieve windows downloads
    with build_step(source_tree, '.download_windows_dependencies.stamp', 'downloading Windows dependencies',
                    ci_mode) as should_run:
        if should_run:
            download_info_win = downloads.DownloadInfo([_ROOT_DIR / 'downloads.ini'])
            downloads.retrieve_downloads(download_info_win, downloads_cache, win_components, True, disable_ssl)
            try:
                downloads.check_downloads(download_info_win, downloads_cache, win_components)
            except downloads.HashMismatchError as exc:
                get_logger().error('File checksum does not match: %s', exc)
                raise


def _step_prune_binaries(source_tree: Path, is_tarball: bool, ci_mode: bool) -> None:
    # Prune binaries
    with build_step(source_tree, '.prune_binaries.stamp', 'pruning binaries', ci_mode) as should_run:
        if should_run:
            pruning_list = (_ROOT_DIR / 'ungoogled-chromium' / 'pruning.list') if is_tarball else (
                    _ROOT_DIR / 'pruning.list')
            unremovable_files = prune_binaries.prune_files(
                source_tree,
                pruning_list.read_text(encoding=ENCODING).splitlines()
            )
            if unremovable_files:
                raise RuntimeError(f'Files could not be pruned: {unremovable_files}')


def _step_unpack_windows_downloads(
        source_tree: Path,
        downloads_cache: Path,
        target: WindowsTarget,
        extractors: dict,
        ci_mode: bool,
) -> None:
    # Determine which Windows dependency components to download/unpack based on target architecture.
    win_components = _get_windows_components(target)

    # Unpack downloads
    with build_step(source_tree, '.unpack_windows_downloads.stamp', 'unpacking Windows downloads',
                    ci_mode) as should_run:
        if should_run:
            directx = source_tree / 'third_party' / 'microsoft_dxheaders' / 'src'
            if directx.exists():
                shutil.rmtree(directx)
                directx.mkdir()
            download_info_win = downloads.DownloadInfo([_ROOT_DIR / 'downloads.ini'])
            downloads.unpack_downloads(download_info_win, downloads_cache, win_components, source_tree, extractors)


def _step_setup_symlinks(source_tree: Path, ci_mode: bool) -> None:
    # Setup 7z symlink (7za -> 7zz)
    with build_step(source_tree, '.setup_7z_symlink.stamp', 'setting up 7z symlink', ci_mode) as should_run:
        if should_run:
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

    # Setup gperf symlink (system gperf -> third_party/gperf/cipd/bin/gperf)
    with build_step(source_tree, '.setup_gperf_symlink.stamp', 'setting up gperf symlink', ci_mode) as should_run:
        if should_run:
            system_gperf_path = shutil.which('gperf')
            if system_gperf_path:
                system_gperf = Path(system_gperf_path)
                gperf_bin_dir = source_tree / 'third_party' / 'gperf' / 'cipd' / 'bin'
                symlink_gperf = gperf_bin_dir / 'gperf'

                gperf_bin_dir.mkdir(parents=True, exist_ok=True)
                if symlink_gperf.exists() or symlink_gperf.is_symlink():
                    symlink_gperf.unlink()

                symlink_gperf.symlink_to(system_gperf)
                get_logger().info('Created symlink: %s -> %s', symlink_gperf, system_gperf)
            else:
                raise RuntimeError('System gperf not found.')


def _step_apply_patches(source_tree: Path, target: WindowsTarget, ci_mode: bool) -> None:
    # Apply patches
    with build_step(source_tree, '.apply_patches.stamp', 'applying patches', ci_mode) as should_run:
        if should_run:
            # First, ungoogled-chromium-patches
            get_logger().info('Applying ungoogled-chromium patches...')
            patches.apply_patches(
                patches.generate_patches_from_series(_ROOT_DIR / 'ungoogled-chromium' / 'patches', resolve=True),
                source_tree,
                patch_bin_path=(source_tree / _PATCH_BIN_RELPATH)
            )
            # Then Windows-specific patches
            get_logger().info('Applying Windows-specific patches...')
            selected_patch_lines = _get_target_optimization_patches(target)
            get_logger().info(
                'Selected optimization patches for %s: %s',
                target.id,
                ', '.join(selected_patch_lines) if selected_patch_lines else 'common only',
            )
            patches.apply_patches(
                _resolve_windows_patches(target),
                source_tree,
                patch_bin_path=(source_tree / _PATCH_BIN_RELPATH)
            )


def _step_apply_domain_substitution(source_tree: Path, is_tarball: bool, ci_mode: bool) -> None:
    # Substitute domains
    with build_step(source_tree, '.apply_domain_substitution.stamp', 'applying domain substitution',
                    ci_mode) as should_run:
        if should_run:
            domain_substitution_list = (
                    _ROOT_DIR / 'ungoogled-chromium' / 'domain_substitution.list') if is_tarball else (
                    _ROOT_DIR / 'domain_substitution.list')
            domain_substitution.apply_substitution(
                _ROOT_DIR / 'ungoogled-chromium' / 'domain_regex.list',
                domain_substitution_list,
                source_tree,
                None
            )


def _step_setup_toolchains(source_tree: Path, target: WindowsTarget, disable_ssl: bool, ci_mode: bool) -> None:
    # Set up Rust toolchain
    rust_dir_dst = setup_rust_toolchain(source_tree, target, ci_mode=ci_mode)

    # Configure Windows Toolchain environment
    setup_windows_toolchain(source_tree, target, ci_mode=ci_mode)

    with build_step(source_tree, '.setup_toolchain.stamp', 'setting up toolchain', ci_mode) as should_run:
        if should_run:
            fix_tool_downloading(source_tree)
            setup_toolchain(source_tree, target, ci_mode=ci_mode)

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

    _compute_build_environment(source_tree, target, rust_dir_dst)


def _step_write_gn_args(
        source_tree: Path,
        out_dir: Path,
        target: WindowsTarget,
        is_tarball: bool,
        ci_mode: bool,
) -> None:
    # Output args.gn
    with build_step(source_tree, '.write_gn_args.stamp', 'writing GN args', ci_mode) as should_run:
        if should_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            gn_flags = _generate_gn_flags(target, is_tarball)
            (out_dir / 'args.gn').write_text(gn_flags, encoding=ENCODING)


def _step_setup_out_dir_symlinks(source_tree: Path, out_dir: Path) -> None:
    # When out_dir is outside source_tree (e.g. CI split-disk layout), GN-generated
    # scripts use relative paths like ../../third_party/... from the build dir.
    # Create a third_party symlink at out_dir/../.. so those paths resolve correctly.
    gn_parent = out_dir.parent.parent
    if gn_parent.resolve() != source_tree.resolve():
        third_party_link = gn_parent / 'third_party'
        if gn_parent.exists() and not third_party_link.exists():
            third_party_link.symlink_to(source_tree / 'third_party')


def _step_run_gn(source_tree: Path, out_dir: Path, ci_mode: bool) -> None:
    # Run GN bootstrap
    with build_step(source_tree, '.gn_bootstrap.stamp', 'running GN bootstrap', ci_mode) as should_run:
        if should_run:
            run_build_process(
                sys.executable,
                'tools/gn/bootstrap/bootstrap.py',
                '-o', str(out_dir / 'gn'),
                '--skip-generate-buildfiles',
                cwd=source_tree,
            )

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
    with build_step(source_tree, '.gn_gen.stamp', 'running GN gen', ci_mode) as should_run:
        if should_run:
            run_build_process(
                str(out_dir / 'gn'),
                'gen',
                str(out_dir),
                '--fail-on-unused-args',
                cwd=source_tree,
            )


def _step_run_ninja(source_tree: Path, out_dir: Path, thread_count: int | None) -> None:
    # Ninja commandline
    ninja_commandline = ['third_party/ninja/ninja']
    if thread_count is not None:
        ninja_commandline.extend(['-j', str(thread_count)])
    ninja_commandline.extend(['-C', str(out_dir), 'chrome', 'chromedriver', 'mini_installer'])

    # Run ninja
    run_build_process(*ninja_commandline, cwd=source_tree)


def _step_package(out_dir: Path) -> None:
    """Package"""
    subprocess.run(
        [sys.executable, 'package.py', '--out-dir', str(out_dir)],
        cwd=_ROOT_DIR,
        check=True,
    )


def run_build_pipeline(args: argparse.Namespace) -> None:
    """Execute the end-to-end Windows cross-compilation build pipeline."""
    target = _resolve_cli_target(args)
    host_arch = get_host_arch()
    if host_arch != 'x64':
        raise RuntimeError(f'Unsupported build host architecture: {host_arch}')

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
    _step_prepare_sources(source_tree, downloads_cache, target, args.tarball, args.disable_ssl_verification, args.ci,
                          extractors)
    _step_download_windows_dependencies(source_tree, downloads_cache, target, args.disable_ssl_verification, args.ci)
    _step_prune_binaries(source_tree, args.tarball, args.ci)
    _step_unpack_windows_downloads(source_tree, downloads_cache, target, extractors, args.ci)
    _step_setup_symlinks(source_tree, args.ci)
    _step_apply_patches(source_tree, target, args.ci)
    _step_apply_domain_substitution(source_tree, args.tarball, args.ci)
    _step_setup_toolchains(source_tree, target, args.disable_ssl_verification, args.ci)
    _step_write_gn_args(source_tree, out_dir, target, args.tarball, args.ci)
    _step_setup_out_dir_symlinks(source_tree, out_dir)
    _step_run_gn(source_tree, out_dir, args.ci)
    _step_run_ninja(source_tree, out_dir, args.thread_count)

    if args.ci:
        _step_package(out_dir)


def main():
    """CLI Entrypoint"""
    parser = _create_argument_parser()
    args = parser.parse_args()
    try:
        run_build_pipeline(args)
    except Exception as exc:
        get_logger().error("Build pipeline failed: %s", exc)
        sys.exit(1)


if __name__ == '__main__':
    main()
