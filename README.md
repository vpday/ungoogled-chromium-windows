# ungoogled-chromium-windows

Cross-compilation setup for building Windows binaries of [ungoogled-chromium](//github.com/Eloston/ungoogled-chromium) on Linux systems.

## Downloads

[Download binaries from the Contributor Binaries website](//ungoogled-software.github.io/ungoogled-chromium-binaries/).

Or install using `winget install --id=eloston.ungoogled-chromium -e`.

**Source Code**: Use a tag via `git checkout` (see building instructions below). The `master` branch is for development and may be unstable.

## Quick Start

This project builds Windows Chromium binaries on Linux through cross-compilation. You need a Linux system (Ubuntu 24.04+ recommended) with at least 80GB free disk space.

```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install -y p7zip-full pkg-config libglib2.0-dev \
    libfuse2 libnss3-dev libcups2-dev libpci-dev libdrm-dev \
    libxkbcommon-dev gperf libkrb5-dev python3 git

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

- **Recommended**: Ubuntu 24.04+, or equivalent
- **Architecture**: x86_64 build machine (for cross-compiling to Windows x64/x86/arm64)

### Disk Space

- Minimum 80GB free space (source tree + build artifacts + build cache)

### System Dependencies

Install these packages before building:

```bash
sudo apt-get update
sudo apt-get install -y \
    zstd p7zip-full pkg-config libglib2.0-dev libfuse2 \
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

The `--ci` flag enables caching. It skips steps if artifacts already exist (e.g., won't re-download source if `build/src/BUILD.gn` exists). Useful for resuming interrupted builds.

### Build Recovery

If the build fails:

**During source download** (git clone phase):
```bash
rm -rf build/download_cache
python3 build.py
```

**Any other failure**:
```bash
# Keep download_cache to avoid re-downloading dependencies
rm -rf build/src build/.stamps
python3 build.py
```

**Complete clean**:
```bash
rm -rf build/
python3 build.py
```

## Build Process Overview

The `build.py` script executes these steps sequentially. Each step creates a `.stamp` file in `build/src/` to enable incremental builds with `--ci`.

1. **Source Acquisition**: Clone Chromium source or extract tarball
2. **Dependency Download**: Fetch Windows-specific dependencies from `downloads.ini`
3. **Binary Pruning**: Remove unnecessary binaries per `pruning.list`
4. **Dependency Unpacking**: Extract downloaded archives to source tree
5. **7-Zip Setup**: Create symlink for installer packaging (`7za` → `7zz`)
6. **Patch Application**:
   - Conditionally add/remove AVX2 optimization patch based on target architecture
   - Apply core ungoogled-chromium patches
   - Apply Windows-specific patches
7. **Domain Substitution**: Replace obfuscated Google domains with real ones
8. **Rust Toolchain Setup**: Configure Rust for Linux host and Windows target
9. **GN Args Generation**: Combine `ungoogled-chromium/flags.gn` + `flags.windows.gn`
10. **Windows Toolchain Setup**: Configure Windows SDK and Visual Studio tools
11. **Additional Toolchain Setup**:
    - Fix domain references in tool download scripts
    - Download rc binary for cross-compilation
    - Set up LLVM environment variables
12. **GN Bootstrap**: Build GN build system
13. **GN Gen**: Generate Ninja build files
14. **Ninja Build**: Compile `chrome`, `chromedriver`, `mini_installer`
15. **Packaging** (CI mode only): Create distribution archives

Each step can be skipped if its stamp file exists, enabling fast recovery from build failures.

## CI Builds

This project uses GitHub Actions for automated builds. The workflow splits compilation into 16 sequential stages to work around the 6-hour job timeout.

See `.github/workflows/main.yml` and `.github/actions/prepare/action.yml` for the complete CI setup. The prepare action installs system dependencies and sets up the build environment on `ubuntu-latest` runners.

## Developer Guide

For patch development workflow (modifying patches using quilt), see [ungoogled-chromium's developing.md](https://github.com/ungoogled-software/ungoogled-chromium/blob/master/docs/developing.md).

The sections below cover dependency maintenance specific to this Windows cross-compilation build.

### Updating Dependencies

All dependency versions are defined in `downloads.ini`. Dependencies are organized into three categories:

#### Core Build Tools

**LLVM Toolchain** (`llvm`)

1. Get version from `build/src/DEPS` by searching for `src/third_party/llvm-build/Release+Asserts`
1. Check [LLVM releases](https://github.com/llvm/llvm-project/releases/) for the version
2. Download `LLVM-VERSION-Linux-X64.tar.xz`
3. Get SHA-256 checksum: `sha256sum LLVM-VERSION-Linux-X64.tar.xz`
4. Update `downloads.ini` section `[llvm]`:
   - `version = VERSION`
   - `sha256 = CHECKSUM`

**Ninja** (`ninja`)

1. Check [Ninja releases](https://github.com/ninja-build/ninja/releases/) for the latest version
2. Download `ninja-linux.zip`
3. Get SHA-256 checksum and update `downloads.ini` section `[ninja]`:
   - `version = VERSION`
   - `sha256 = CHECKSUM`

**7-Zip for Linux** (`7zip-linux`)

1. Check [7-Zip releases](https://www.7-zip.org/download.html) for Linux x64 builds
2. Download `7zVERSION-linux-x64.tar.xz`
3. Get SHA-256 checksum and update `downloads.ini` section `[7zip-linux]`:
   - `version = VERSION` (e.g., `2501` for 25.01)
   - `sha256 = CHECKSUM`

**Node.js** (`nodejs`)

1. Get `NODE_VERSION` from `build/src/third_party/node/update_node_binaries`
2. Download `node-vVERSION-linux-x64.tar.xz` from [NodeJS website](https://nodejs.org/dist/)
3. Update `downloads.ini` `[nodejs]` with version and SHA-256 checksum

**esbuild** (`esbuild`)

1. Get `devtools_frontend_revision` from `build/src/DEPS`
2. Visit `https://chromium.googlesource.com/devtools/devtools-frontend/+/REVISION/DEPS`
3. Search for `third_party/esbuild` to get version (e.g., `version:3@0.25.1.chromium.2` → `0.25.1`)
4. Download from npm: `https://registry.npmjs.org/@esbuild/linux-x64/-/linux-x64-VERSION.tgz`
5. Update `downloads.ini` `[esbuild]` with version and SHA-256 checksum

#### Windows Platform Dependencies

**DirectX Headers** (`directx-headers`)

1. Get commit hash from `build/src/DEPS` by searching for `src/third_party/microsoft_dxheaders/src`
2. Update `downloads.ini` `[directx-headers]` with `version = COMMIT_HASH`

**WebAuthn Headers** (`webauthn`)

1. Get commit hash from `build/src/DEPS` by searching for `src/third_party/microsoft_webauthn/src`
2. Update `downloads.ini` `[webauthn]` with `version = COMMIT_HASH`

#### Rust Toolchain

The Rust toolchain consists of:
- **Host toolchains**: `rust-x64`, `rust-x86`, `rust-arm` (for Linux build machine)
- **Windows targets**: `rust-std-windows-x64`, `rust-std-windows-x86`, `rust-std-windows-arm` (for cross-compilation)
- **Windows crate**: `rust-windows-create` (system API bindings)

**Update process:**

1. Check `RUST_REVISION` in `build/src/tools/rust/update_rust.py`
```bash
grep RUST_REVISION build/src/tools/rust/update_rust.py
```

2. Get commit date from `https://github.com/rust-lang/rust/commit/RUST_REVISION`
   - Example: Revision `abc123...` corresponds to date `2025-12-02`

3. Download all Rust components from `https://static.rust-lang.org/dist/2025-12-02/`:

**Host toolchains** (Linux):
```bash
# x64 host
wget https://static.rust-lang.org/dist/2025-12-02/rust-nightly-x86_64-unknown-linux-gnu.tar.xz
sha256sum rust-nightly-x86_64-unknown-linux-gnu.tar.xz

# x86 host (for 32-bit builds)
wget https://static.rust-lang.org/dist/2025-12-02/rust-nightly-i686-unknown-linux-gnu.tar.xz
sha256sum rust-nightly-i686-unknown-linux-gnu.tar.xz

# ARM host (for ARM builds)
wget https://static.rust-lang.org/dist/2025-12-02/rust-nightly-aarch64-unknown-linux-gnu.tar.xz
sha256sum rust-nightly-aarch64-unknown-linux-gnu.tar.xz
```

**Windows targets** (cross-compilation):
```bash
# x64 target
wget https://static.rust-lang.org/dist/2025-12-02/rust-std-nightly-x86_64-pc-windows-msvc.tar.xz
sha256sum rust-std-nightly-x86_64-pc-windows-msvc.tar.xz

# x86 target
wget https://static.rust-lang.org/dist/2025-12-02/rust-std-nightly-i686-pc-windows-msvc.tar.xz
sha256sum rust-std-nightly-i686-pc-windows-msvc.tar.xz

# ARM64 target
wget https://static.rust-lang.org/dist/2025-12-02/rust-std-nightly-aarch64-pc-windows-msvc.tar.xz
sha256sum rust-std-nightly-aarch64-pc-windows-msvc.tar.xz
```

4. Extract a host toolchain and verify version:
```bash
tar xzf rust-nightly-x86_64-unknown-linux-gnu.tar.xz
./rust-nightly-x86_64-unknown-linux-gnu/rustc/bin/rustc -V
# Output: rustc 1.93.0-nightly (1d60f9e07 2025-12-01)
```

5. Update `downloads.ini` sections:
   - `[rust-x64]`, `[rust-x86]`, `[rust-arm]`: Update `version` and `sha256`
   - `[rust-std-windows-x64]`, `[rust-std-windows-x86]`, `[rust-std-windows-arm]`: Update `version` and `sha256`

6. Update `patches/ungoogled-chromium/windows/windows-fix-building-with-rust.patch`:
   - Replace the Rust version string to match the output from step 4
   - Example: Change `rustc_version = ""` to `rustc_version = "rustc 1.93.0-nightly (1d60f9e07 2025-12-01)"`

**Windows Rust Crate** (`rust-windows-create`)

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

The Windows cross-compilation toolchain configuration is in `win_toolchain.json`. This file defines the Visual Studio and Windows SDK packages needed for cross-compilation.

**When to update:**
- When Chromium version changes (update `chromium_version`)
- When Visual Studio or Windows SDK version changes in Chromium upstream

**Configuration structure:**

`win_toolchain.json` contains the following fields:

```json
{
  "variables": {
    "chromium_version": "145.0.7632.45",
    "sdk_version": "10.0.26100.0",
    "vs_version": "2022",
    "repo": "vpday/chromium-win-toolchain-builder"
  },
  "win-toolchain": {
    "zip_filename": "ec6812dcab",
    "sha512": "...",
    "files": []
  },
  "win-toolchain-noarm": {
    "zip_filename": "1c78b2a976",
    "sha512": "...",
    "files": []
  }
}
```

**Field descriptions:**
- `variables.chromium_version`: Must match `ungoogled-chromium/chromium_version.txt`
- `variables.sdk_version`: Windows SDK version
- `variables.vs_version`: Visual Studio version year
- `variables.repo`: Toolchain source repository
- `win-toolchain`: Full toolchain with ARM support (for arm64 builds)
  - Split into 2 files (.tar.001, .tar.002) due to GitHub release size limits
- `win-toolchain-noarm`: Lightweight toolchain without ARM support (for x64 and x86 builds)
  - Single .tar file, faster download

**Update process:**

1. **Check current Chromium version**

```bash
cat ungoogled-chromium/chromium_version.txt
```

Update `variables.chromium_version` in `win_toolchain.json` to match this version.

2. **Check for new toolchain releases**

Visit: `https://github.com/vpday/chromium-win-toolchain-builder/releases/tag/VERSION`

The release page provides:
- Tar archives: `win_toolchain_chromium-VERSION_vs-YEAR_sdk-SDK.tar.001/002` (with ARM) or `...noarm.tar` (without ARM)
- Zip filenames: `ec6812dcab.zip` (with ARM), `1c78b2a976.zip` (without ARM)
- SHA-256 and SHA-512 checksums for both tar and zip files

3. **Get zip information from releases page**

From the release page, copy:
- Zip filename (e.g., `ec6812dcab.zip` for full toolchain, `1c78b2a976.zip` for noarm)
- Zip SHA-512 checksum

These will be used for `zip_filename` and `sha512` fields in `win_toolchain.json`.

4. **Get tar file checksums from releases page**

From the release page, copy SHA-256 checksums for each tar file:
- Full toolchain: checksums for `.tar.001` and `.tar.002`
- Noarm toolchain: checksum for `.tar`

These will be used for the `sha256` field in the `files[]` array in `win_toolchain.json`.

5. **Update win_toolchain.json**

Update `variables` section:
```json
"variables": {
  "chromium_version": "145.0.7632.45",
  "sdk_version": "10.0.26100.0",
  "vs_version": "2022"
}
```

Make sure `chromium_version` matches `ungoogled-chromium/chromium_version.txt`.

Update `win-toolchain` and `win-toolchain-noarm` sections:
- `zip_filename`: from step 3
- `sha512`: from step 3
- `files[].sha256`: from step 4

## Technical Details

### Cross-Compilation Setup

This project downloads a complete Windows toolchain (LLVM, Windows SDK, Rust) and builds Windows binaries on Linux. The process:

1. Downloads Linux-native build tools (LLVM, Ninja, Node.js)
2. Downloads Windows cross-compilation toolchain via `win_toolchain.json`
3. Downloads Rust toolchain (Linux host + Windows targets)
4. Configures GN with `target_os = "win"` and `is_clang = true`
5. Builds using the cross-compilation toolchain

### Architecture Support

The build system supports three Windows target architectures:

- **x64** (default): 64-bit Windows, includes AVX2 optimizations
- **x86**: 32-bit Windows, requires multilib support on build machine
- **arm64**: ARM64 Windows

### AVX2 Optimizations

For x64 builds, the system automatically applies AVX2 optimizations via `patches/ungoogled-chromium/windows/windows-enable-avx2-optimizations.patch`. This patch is conditionally added to `patches/series` based on the target architecture.

## License

See [LICENSE](LICENSE)
