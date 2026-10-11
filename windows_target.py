"""Canonical Windows build target facts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WindowsTarget:
    id: str
    clone_platform: str
    gn_target_cpu: str
    sysroot_arch: str
    windows_rust_target: str
    windows_rust_std_selector: str
    package_filter: str
    requires_arm_toolchain: bool
    linux_rust_std_selector: str | None = None
    linux_rust_target: str | None = None


SUPPORTED_TARGET_IDS = ("x64", "x86", "arm64")

_TARGETS = {
    "x64": WindowsTarget(
        id="x64",
        clone_platform="win64",
        gn_target_cpu="x64",
        sysroot_arch="amd64",
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
        windows_rust_target="i686-pc-windows-msvc",
        windows_rust_std_selector="rust-std-windows-x86",
        package_filter="32bit",
        requires_arm_toolchain=False,
        linux_rust_std_selector="rust-std-linux-x86",
        linux_rust_target="i686-unknown-linux-gnu",
    ),
    "arm64": WindowsTarget(
        id="arm64",
        clone_platform="win-arm64",
        gn_target_cpu="arm64",
        sysroot_arch="arm64",
        windows_rust_target="aarch64-pc-windows-msvc",
        windows_rust_std_selector="rust-std-windows-arm",
        package_filter="arm",
        requires_arm_toolchain=True,
    ),
}


def _validate_targets():
    if tuple(_TARGETS) != SUPPORTED_TARGET_IDS:
        raise RuntimeError("Windows target registry does not match supported target IDs")

    required_string_fields = (
        "id",
        "clone_platform",
        "gn_target_cpu",
        "sysroot_arch",
        "windows_rust_target",
        "windows_rust_std_selector",
        "package_filter",
    )
    for target_id, target in _TARGETS.items():
        if target.id != target_id:
            raise RuntimeError(f"Windows target registry key mismatch: {target_id}")
        if any(not getattr(target, field_name) for field_name in required_string_fields):
            raise RuntimeError(f"Windows target row is incomplete: {target_id}")
        if bool(target.linux_rust_std_selector) != bool(target.linux_rust_target):
            raise RuntimeError(f"Windows target linux rust std configuration mismatch: {target_id}")


_validate_targets()


def resolve_windows_target(target_id: str) -> WindowsTarget:
    """Resolve one canonical target ID without applying boundary aliases or defaults."""
    if not isinstance(target_id, str) or target_id not in _TARGETS:
        accepted = ", ".join(SUPPORTED_TARGET_IDS)
        raise ValueError(f"Unsupported Windows target {target_id!r}; expected one of: {accepted}")
    return _TARGETS[target_id]
