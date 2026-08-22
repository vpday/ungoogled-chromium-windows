"""Canonical Windows build target facts."""

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class WindowsTarget:
    id: str
    clone_platform: str
    gn_target_cpu: str
    sysroot_arch: str
    linux_rust_arch: str
    linux_rust_target: str
    rust_download_selector: str
    windows_rust_target: str
    windows_rust_std_selector: str
    package_filter: str
    requires_arm_toolchain: bool


SUPPORTED_TARGET_IDS = ("x64", "x86", "arm64")

_TARGETS = {
    "x64": WindowsTarget(
        id="x64",
        clone_platform="win64",
        gn_target_cpu="x64",
        sysroot_arch="amd64",
        linux_rust_arch="x86_64",
        linux_rust_target="x86_64-unknown-linux-gnu",
        rust_download_selector="rust-x64",
        windows_rust_target="x86_64-pc-windows-msvc",
        windows_rust_std_selector="rust-std-windows-x64",
        package_filter="64bit",
        requires_arm_toolchain=False,
    ),
    "x86": WindowsTarget(
        id="x86",
        clone_platform="win32",
        gn_target_cpu="x86",
        sysroot_arch="i386",
        linux_rust_arch="i686",
        linux_rust_target="i686-unknown-linux-gnu",
        rust_download_selector="rust-x86",
        windows_rust_target="i686-pc-windows-msvc",
        windows_rust_std_selector="rust-std-windows-x86",
        package_filter="32bit",
        requires_arm_toolchain=False,
    ),
    "arm64": WindowsTarget(
        id="arm64",
        clone_platform="win-arm64",
        gn_target_cpu="arm64",
        sysroot_arch="arm64",
        linux_rust_arch="aarch64",
        linux_rust_target="aarch64-unknown-linux-gnu",
        rust_download_selector="rust-arm",
        windows_rust_target="aarch64-pc-windows-msvc",
        windows_rust_std_selector="rust-std-windows-arm",
        package_filter="arm",
        requires_arm_toolchain=True,
    ),
}


def _validate_targets():
    if tuple(_TARGETS) != SUPPORTED_TARGET_IDS:
        raise RuntimeError("Windows target registry does not match supported target IDs")

    string_fields = tuple(
        field.name for field in fields(WindowsTarget)
        if field.name != "requires_arm_toolchain"
    )
    for target_id, target in _TARGETS.items():
        if target.id != target_id:
            raise RuntimeError(f"Windows target registry key mismatch: {target_id}")
        if any(not getattr(target, field_name) for field_name in string_fields):
            raise RuntimeError(f"Windows target row is incomplete: {target_id}")


_validate_targets()


def resolve_windows_target(target_id: str) -> WindowsTarget:
    """Resolve one canonical target ID without applying boundary aliases or defaults."""
    if not isinstance(target_id, str) or target_id not in _TARGETS:
        accepted = ", ".join(SUPPORTED_TARGET_IDS)
        raise ValueError(f"Unsupported Windows target {target_id!r}; expected one of: {accepted}")
    return _TARGETS[target_id]
