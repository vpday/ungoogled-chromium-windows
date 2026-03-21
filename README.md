# ungoogled-chromium-windows

This repository cross-compiles Windows binaries of [ungoogled-chromium](https://github.com/Eloston/ungoogled-chromium) on Linux.

## Downloads

[Download binaries from the Contributor Binaries website](https://ungoogled-software.github.io/ungoogled-chromium-binaries/).

Or install using `winget install --id=eloston.ungoogled-chromium -e`.

Use a tag when building a release. The `master` branch is for development and may be unstable.

## Quick Start

This project builds Windows Chromium binaries on Linux. You need a Linux system
(Ubuntu 24.04+ recommended) with at least 80GB free disk space. Install the
packages listed in [System Dependencies](#system-dependencies) first.

```bash
# Clone repository
git clone --recurse-submodules https://github.com/vpday/ungoogled-chromium-windows.git
cd ungoogled-chromium-windows

# Checkout a release tag
git checkout --recurse-submodules TAG_OR_BRANCH_HERE

# Build (this will take several hours)
python3 build.py

# Create distribution packages
python3 package.py
```

A zip archive and installer will be created under `build/`.

## System Requirements

### Linux Distribution

- Recommended distro: Ubuntu 24.04+, or equivalent
- Build machine architecture: x86_64 (for cross-compiling to Windows x64/x86/arm64)

### Disk Space

- Minimum 80GB free space (source tree + build artifacts + build cache)

### System Dependencies

Install these packages before building:

```bash
sudo apt-get update
sudo apt-get install -y \
    p7zip-full pkg-config libglib2.0-dev libfuse2 libfuse2t64 \
    libnss3-dev libcups2-dev libpci-dev libdrm-dev \
    libxkbcommon-dev gperf libkrb5-dev python3 git
```

For x86 (32-bit) builds, also install:

```bash
sudo dpkg --add-architecture i386
sudo apt-get update
sudo apt-get install -y libc6-dev-i386 linux-libc-dev:i386 \
    gcc-multilib g++-multilib libglib2.0-0:i386 libnss3:i386 \
    libnspr4:i386 libatk1.0-0:i386 libatk-bridge2.0-0:i386 \
    libcups2:i386 libdrm2:i386 libdbus-1-3:i386 libexpat1:i386
```

## Building

### Standard x64 Build

```bash
python3 build.py
python3 package.py
```

### Architecture-Specific Builds

```bash
# 32-bit Windows build
python3 build.py --x86
# ARM64 Windows build
python3 build.py --arm
# Default: 64-bit Windows build
python3 build.py
```

### Build Options

```bash
# Use 16 CPU threads
python3 build.py -j 16
# Enable incremental build (skip completed steps)
python3 build.py --ci
# Use pre-packaged Chromium tarball
python3 build.py --tarball
```

The `--ci` flag turns on stamp-based step skipping. Most completed steps are
skipped when their stamp file already exists, which is useful when resuming an
interrupted build or continuing a multi-stage CI run.

### Build Recovery

If the build fails during source download or the git clone phase, run:
```bash
rm -rf build/download_cache
python3 build.py
```

For most other failures, run:
```bash
# Keep download_cache to avoid re-downloading dependencies
rm -rf build/src
python3 build.py
```

This removes `build/src/.stamps` along with the source tree, which resets most
build steps. `build/.stamps` is separate and only tracks Windows toolchain
extraction state.

For a full clean rebuild, run:
```bash
rm -rf build/
python3 build.py
```

## Build Process Overview

The `build.py` script runs these steps in order. In `--ci` mode, most step
state is stored in `build/src/.stamps`. Windows toolchain extraction is the
exception: it uses `build/.stamps/.vs_toolchain_updated_{target_arch}.stamp`.
That split exists to support GitHub Actions multi-stage builds, where the VS
toolchain setup may need to run at the start of each stage while the other
steps usually only need to run once.

1. Clone Chromium source or extract a tarball.
2. Download Windows-specific dependencies from `downloads.ini`.
3. Remove unnecessary binaries listed in `pruning.list`.
4. Extract downloaded archives into the source tree.
5. Create the installer packaging symlink (`7za` → `7zz`).
6. Apply patches:
   - Conditionally add/remove AVX2 optimization patch based on target architecture
   - Apply core ungoogled-chromium patches
   - Apply Windows-specific patches
7. Replace obfuscated Google domains with real ones.
8. Configure Rust for the Linux host and the Windows target.
9. Combine `ungoogled-chromium/flags.gn` and `flags.windows.gn`.
10. Configure the Windows SDK and Visual Studio tools.
11. Run the remaining toolchain setup:
    - Fix domain references in tool download scripts
    - Download rc binary for cross-compilation
    - Set up LLVM environment variables
12. Build the GN build system.
13. Generate Ninja build files.
14. Compile `chrome`, `chromedriver`, and `mini_installer`.
15. In CI mode, `build.py` calls `package.py` automatically.
    For local builds, run `python3 package.py` yourself.

Most of these steps can be skipped when their stamp file already exists, which
makes recovery much faster after a failed build.

## CI Builds

The CI pipeline is split into four workflows:

- `.github/workflows/build-x64.yml` - x64 build
- `.github/workflows/build-x86.yml` - x86 build
- `.github/workflows/build-arm.yml` - arm64 build
- `.github/workflows/publish-release.yml` - release aggregation and publishing

Each architecture workflow keeps the existing 8-stage recovery chain to work around the 6-hour GitHub Actions job timeout. A failed or retried x64/x86/arm build only requires rerunning that architecture's workflow, while the release remains gated on all three architectures being available for the same tag.

The publish workflow listens for successful architecture builds, finds the latest successful x64/x86/arm runs for the same tag, downloads their final `chromium`, `chromium-x86`, and `chromium-arm` artifacts, and publishes a single GitHub Release once all three are present. If one architecture is still missing, the publish workflow exits without creating a partial release.

See `.github/workflows/build-x64.yml`, `.github/workflows/build-x86.yml`, `.github/workflows/build-arm.yml`, `.github/workflows/publish-release.yml`, and `.github/actions/prepare/action.yml` for the complete CI setup.

## Developer Guide

For quilt-based patch development, see [ungoogled-chromium's developing.md](https://github.com/ungoogled-software/ungoogled-chromium/blob/master/docs/developing.md).

### Updating Dependencies

All dependency versions are defined in `downloads.ini`. Dependencies are organized into three categories:

#### Core Build Tools

##### LLVM toolchain (`llvm`)

1. Get the version from `build/src/DEPS` by searching for `src/third_party/llvm-build/Release+Asserts`
2. Check [LLVM releases](https://github.com/llvm/llvm-project/releases/) for that version
3. Download `LLVM-VERSION-Linux-X64.tar.xz`
4. Get the SHA-256 checksum: `sha256sum LLVM-VERSION-Linux-X64.tar.xz`
5. Update `downloads.ini` section `[llvm]`:
   - `version = VERSION`
   - `sha256 = CHECKSUM`

##### Ninja (`ninja`)

1. Check [Ninja releases](https://github.com/ninja-build/ninja/releases/) for the latest version
2. Download `ninja-linux.zip`
3. Get SHA-256 checksum and update `downloads.ini` section `[ninja]`:
   - `version = VERSION`
   - `sha256 = CHECKSUM`

##### 7-Zip for Linux (`7zip-linux`)

1. Check [7-Zip releases](https://www.7-zip.org/download.html) for Linux x64 builds
2. Download `7zVERSION-linux-x64.tar.xz`
3. Get SHA-256 checksum and update `downloads.ini` section `[7zip-linux]`:
   - `version = VERSION` (e.g., `2501` for 25.01)
   - `sha256 = CHECKSUM`

##### Node.js (`nodejs`)

1. Get `NODE_VERSION` from `build/src/third_party/node/update_node_binaries`
2. Download `node-vVERSION-linux-x64.tar.xz` from [NodeJS website](https://nodejs.org/dist/)
3. Update `downloads.ini` `[nodejs]` with version and SHA-256 checksum

##### esbuild (`esbuild`)

1. Get `devtools_frontend_revision` from `build/src/DEPS`
2. Visit `https://chromium.googlesource.com/devtools/devtools-frontend/+/REVISION/DEPS`
3. Search for `third_party/esbuild` to get version (e.g., `version:3@0.25.1.chromium.2` → `0.25.1`)
4. Download from npm: `https://registry.npmjs.org/@esbuild/linux-x64/-/linux-x64-VERSION.tgz`
5. Update `downloads.ini` `[esbuild]` with version and SHA-256 checksum

#### Windows Platform Dependencies

##### DirectX headers (`directx-headers`)

1. Get commit hash from `build/src/DEPS` by searching for `src/third_party/microsoft_dxheaders/src`
2. Update `downloads.ini` `[directx-headers]` with `version = COMMIT_HASH`

##### WebAuthn headers (`webauthn`)

1. Get commit hash from `build/src/DEPS` by searching for `src/third_party/microsoft_webauthn/src`
2. Update `downloads.ini` `[webauthn]` with `version = COMMIT_HASH`

#### Rust Toolchain

The Rust toolchain consists of:
- Linux Rust archives: `rust-x64`, `rust-x86`, `rust-arm`
- Windows targets: `rust-std-windows-x64`, `rust-std-windows-x86`, `rust-std-windows-arm` (for cross-compilation)
- Windows crate: `rust-windows-create` (system API bindings)

The build does not download all of them for every target:
- Default `x64`: `rust-x64`, `rust-std-windows-x64`, `rust-windows-create`
- `--x86`: `rust-x64`, `rust-x86`, `rust-std-windows-x86`, `rust-windows-create`
- `--arm`: `rust-x64`, `rust-arm`, `rust-std-windows-arm`, `rust-windows-create`

##### Rust update process

1. Check `RUST_REVISION` in `build/src/tools/rust/update_rust.py`
```bash
grep RUST_REVISION build/src/tools/rust/update_rust.py
```

2. Get commit date from `https://github.com/rust-lang/rust/commit/RUST_REVISION`
   - Example: Revision `abc123...` corresponds to date `2026-01-30`

3. Download `https://static.rust-lang.org/dist/2026-01-30/channel-rust-nightly.toml`. Use the matching `xz_hash` value from that manifest as the `sha256` you put in `downloads.ini`. That is the SHA-256 for the `.tar.xz` archive, so you do not need to download every Rust archive just to run `sha256sum`.

Linux Rust archives:
```text
rust-nightly-x86_64-unknown-linux-gnu.tar.xz -> [pkg.rust.target.x86_64-unknown-linux-gnu].xz_hash
rust-nightly-i686-unknown-linux-gnu.tar.xz -> [pkg.rust.target.i686-unknown-linux-gnu].xz_hash
rust-nightly-aarch64-unknown-linux-gnu.tar.xz -> [pkg.rust.target.aarch64-unknown-linux-gnu].xz_hash
```

Windows targets for cross-compilation:
```text
rust-std-nightly-x86_64-pc-windows-msvc.tar.xz -> [pkg.rust-std.target.x86_64-pc-windows-msvc].xz_hash
rust-std-nightly-i686-pc-windows-msvc.tar.xz -> [pkg.rust-std.target.i686-pc-windows-msvc].xz_hash
rust-std-nightly-aarch64-pc-windows-msvc.tar.xz -> [pkg.rust-std.target.aarch64-pc-windows-msvc].xz_hash
```

4. If you want to verify the nightly version string, download one Linux Rust archive and extract it:
```bash
wget https://static.rust-lang.org/dist/2026-01-30/rust-nightly-x86_64-unknown-linux-gnu.tar.xz
tar xf rust-nightly-x86_64-unknown-linux-gnu.tar.xz
./rust-nightly-x86_64-unknown-linux-gnu/rustc/bin/rustc -V
# Output: rustc-1.95.0-nightly
```

5. Update `downloads.ini` sections:
   - `[rust-x64]`, `[rust-x86]`, `[rust-arm]`: Update `version` and `sha256`
   - `[rust-std-windows-x64]`, `[rust-std-windows-x86]`, `[rust-std-windows-arm]`: Update `version` and `sha256`

6. Update `patches/ungoogled-chromium/windows/windows-fix-building-with-rust.patch`:
   - Replace the `rustc_version` string with the nightly version string for that toolchain
   - Example: Change `rustc_version = ""` to `rustc_version = "rustc-1.95.0-nightly"`

##### Windows Rust crate (`rust-windows-create`)

1. Check version in `build/src/third_party/rust/windows_x86_64_msvc/`
2. Download from GitHub: `https://github.com/microsoft/windows-rs/archive/refs/tags/VERSION.zip`
3. Get SHA-512 checksum:
```bash
sha512sum windows-rs-VERSION.zip
```
4. Update `downloads.ini` section `[rust-windows-create]`:
   - `version = VERSION`
   - `sha512 = CHECKSUM`
5. If version changed, update `patches/ungoogled-chromium/windows/windows-fix-building-with-rust.patch` accordingly

### Updating Windows Toolchain

The Windows cross-compilation toolchain configuration lives in `win_toolchain.json`. It defines the Visual Studio and Windows SDK packages used for cross-compilation.

Update `win_toolchain.json` when:
- When Chromium version changes (update `chromium_version`)
- When Visual Studio or Windows SDK version changes in Chromium upstream

`win_toolchain.json` has the following fields:

```json
{
  "variables": {
    "chromium_version": "146.0.7680.153",
    "sdk_version": "10.0.26100.0",
    "vs_version": "2022",
    "repo": "vpday/chromium-win-toolchain-builder"
  },
  "win-toolchain": {
    "zip_filename": "a3769f983f",
    "sha512": "...",
    "files": []
  },
  "win-toolchain-noarm": {
    "zip_filename": "b958251984",
    "sha512": "...",
    "files": []
  }
}
```

Field descriptions:
- `variables.chromium_version`: Must match `ungoogled-chromium/chromium_version.txt`
- `variables.sdk_version`: Windows SDK version
- `variables.vs_version`: Visual Studio version year
- `variables.repo`: Toolchain source repository
- `win-toolchain`: Full toolchain with ARM support (for arm64 builds)
  - Split into 2 files (.tar.001, .tar.002) due to GitHub release size limits
- `win-toolchain-noarm`: Lightweight toolchain without ARM support (for x64 and x86 builds)
  - Single .tar file, faster download

##### Windows toolchain update process

1. Check the current Chromium version.

```bash
cat ungoogled-chromium/chromium_version.txt
```

Update `variables.chromium_version` in `win_toolchain.json` to match this version.

2. Check for new toolchain releases.

Visit: `https://github.com/vpday/chromium-win-toolchain-builder/releases/tag/VERSION`

From the release page, collect:
- Tar archives: `win_toolchain_chromium-VERSION_vs-YEAR_sdk-SDK.tar.001/002` (with ARM) or `...noarm.tar` (without ARM)
- Zip filenames: `a3769f983f.zip` (with ARM), `b958251984.zip` (without ARM)
- SHA-256 and SHA-512 checksums for both tar and zip files

3. Get zip information from the releases page.

From the release page, copy:
- Zip filename (e.g., `a3769f983f.zip` for full toolchain, `b958251984.zip` for noarm)
- Zip SHA-512 checksum

Use these values for the `zip_filename` and `sha512` fields in `win_toolchain.json`.

4. Get tar file checksums from the releases page.

From the release page, copy SHA-256 checksums for each tar file:
- Full toolchain: checksums for `.tar.001` and `.tar.002`
- Noarm toolchain: checksum for `.tar`

Use these values for the `sha256` field in the `files[]` array in `win_toolchain.json`.

5. Update `win_toolchain.json`.

Update `variables` section:
```json
{
  "variables": {
    "chromium_version": "146.0.7680.153",
    "sdk_version": "10.0.26100.0",
    "vs_version": "2022"
  }
}
```

Make sure `chromium_version` matches `ungoogled-chromium/chromium_version.txt`.

Update `win-toolchain` and `win-toolchain-noarm` sections:
- `zip_filename`: from step 3
- `sha512`: from step 3
- `files[].sha256`: from step 4

## Technical Details

### Cross-Compilation Setup

This project downloads a complete Windows toolchain (LLVM, Windows SDK, Rust)
and builds Windows binaries on Linux. The build works like this:

1. Downloads Linux-native build tools (LLVM, Ninja, Node.js)
2. Downloads Windows cross-compilation toolchain via `win_toolchain.json`
3. Downloads Rust toolchain (Linux host + Windows targets)
4. Configures GN with `target_os = "win"` and `is_clang = true`
5. Builds using the cross-compilation toolchain

### Architecture Support

The build system supports three Windows target architectures:

- x64 (default): 64-bit Windows, includes AVX2 optimizations
- x86: 32-bit Windows, requires multilib support on build machine
- arm64: ARM64 Windows

### AVX2 Optimizations

The AVX2 optimization patch is based on work from
[RobRich999/Chromium_Clang](https://github.com/RobRich999/Chromium_Clang).

For x64 builds, the system automatically applies AVX2 optimizations via
`patches/ungoogled-chromium/windows/windows-enable-avx2-optimizations.patch`.
This patch is conditionally added to `patches/series` based on the target
architecture.

## License

See [LICENSE](LICENSE)
