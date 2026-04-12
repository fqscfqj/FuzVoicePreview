from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
import re
import ctypes

from .translation import QCoreApplication


_DLL_HANDLES: list[object] = []


@dataclass(frozen=True)
class RuntimeDiagnostics:
    vendor_dir: Path
    pyav_available: bool
    qt_multimedia_available: bool
    messages: tuple[str, ...]


def configure_runtime() -> RuntimeDiagnostics:
    package_dir = Path(__file__).resolve().parent
    vendor_dir = package_dir / "vendor"

    _extend_sys_path(vendor_dir)
    _register_dll_directories(vendor_dir)
    _preload_native_libraries(vendor_dir)

    messages: list[str] = []
    messages.extend(_runtime_compatibility_messages(vendor_dir))
    pyav_available = _module_available("av", messages)
    qt_multimedia_available = _module_available("PyQt6.QtMultimedia", messages)

    return RuntimeDiagnostics(
        vendor_dir=vendor_dir,
        pyav_available=pyav_available,
        qt_multimedia_available=qt_multimedia_available,
        messages=tuple(messages),
    )


def _extend_sys_path(vendor_dir: Path) -> None:
    if not vendor_dir.exists():
        return

    candidates = [vendor_dir, _select_vendor_site_packages(vendor_dir), vendor_dir / "python"]
    for candidate in candidates:
        candidate_str = str(candidate)
        if candidate.exists() and candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)


def _register_dll_directories(vendor_dir: Path) -> None:
    if not vendor_dir.exists():
        return

    site_packages_dir = _select_vendor_site_packages(vendor_dir)
    candidates = [
        vendor_dir,
        vendor_dir / "bin",
        site_packages_dir / "av.libs",
    ]
    candidates.extend(_discover_qt_dll_directories())

    for candidate in _dedupe_paths(candidates):
        if not candidate.exists():
            continue
        _prepend_process_path(candidate)
        if hasattr(os, "add_dll_directory"):
            try:
                _DLL_HANDLES.append(os.add_dll_directory(str(candidate)))
            except OSError:
                continue


def _module_available(module_name: str, messages: list[str]) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except Exception as exc:
        messages.append(
            QCoreApplication.translate("RuntimeDiagnostics", "{module_name}: {error}").format(
                module_name=module_name,
                error=exc,
            )
        )
        return False


def _discover_qt_dll_directories() -> list[Path]:
    spec = importlib.util.find_spec("PyQt6")
    if spec is None or not spec.submodule_search_locations:
        return []

    candidates: list[Path] = []
    for location in spec.submodule_search_locations:
        package_dir = Path(location)
        candidates.extend(
            [
                package_dir,
                package_dir / "Qt6" / "bin",
                package_dir / "Qt6" / "plugins",
                package_dir / "Qt6" / "plugins" / "multimedia",
            ]
        )
    return candidates


def _prepend_process_path(path: Path) -> None:
    path_str = str(path)
    current = os.environ.get("PATH", "")
    entries = current.split(os.pathsep) if current else []
    if path_str not in entries:
        os.environ["PATH"] = path_str if not current else path_str + os.pathsep + current


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in paths:
        normalized = path.resolve(strict=False)
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _preload_native_libraries(vendor_dir: Path) -> None:
    if os.name != "nt":
        return

    # Let the loader resolve Python/runtime DLLs from vendor/bin on demand.
    # Preloading them can conflict with MO2's embedded plugin_python host.
    site_packages_dir = _select_vendor_site_packages(vendor_dir)
    dll_dirs = _dedupe_paths(
        [
            site_packages_dir / "av.libs",
            *_discover_qt_dll_directories(),
        ]
    )
    for dll_dir in dll_dirs:
        if not dll_dir.exists():
            continue
        for dll_path in sorted(dll_dir.glob("*.dll")):
            try:
                ctypes.WinDLL(str(dll_path))
            except OSError:
                continue


def _runtime_compatibility_messages(vendor_dir: Path) -> list[str]:
    messages = [
        QCoreApplication.translate("RuntimeDiagnostics", "Python runtime: {version}").format(
            version=sys.version.split()[0]
        )
    ]

    wheel_file = next(_select_vendor_site_packages(vendor_dir).glob("av-*.dist-info/WHEEL"), None)
    if wheel_file is None:
        messages.append(QCoreApplication.translate("RuntimeDiagnostics", "Bundled PyAV wheel metadata was not found."))
        return messages

    try:
        wheel_text = wheel_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        messages.append(
            QCoreApplication.translate(
                "RuntimeDiagnostics", "Bundled PyAV wheel metadata could not be read: {error}"
            ).format(error=exc)
        )
        return messages

    tag_match = re.search(r"^Tag:\s*(.+)$", wheel_text, re.MULTILINE)
    if tag_match is None:
        messages.append(QCoreApplication.translate("RuntimeDiagnostics", "Bundled PyAV wheel tag is missing."))
        return messages

    tag = tag_match.group(1).strip()
    messages.append(QCoreApplication.translate("RuntimeDiagnostics", "Bundled PyAV wheel tag: {tag}").format(tag=tag))

    required = _minimum_python_for_tag(tag)
    if required is not None and sys.version_info < required:
        messages.append(
            QCoreApplication.translate(
                "RuntimeDiagnostics",
                "Bundled PyAV wheel requires Python >= {required_major}.{required_minor}, current runtime is {runtime_major}.{runtime_minor}.",
            ).format(
                required_major=required[0],
                required_minor=required[1],
                runtime_major=sys.version_info.major,
                runtime_minor=sys.version_info.minor,
            )
        )

    return messages


def _minimum_python_for_tag(tag: str) -> tuple[int, int] | None:
    match = re.match(r"cp(\d)(\d+)-abi3-", tag)
    if match is not None:
        return int(match.group(1)), int(match.group(2))

    match = re.match(r"cp(\d)(\d+)-cp\d\d-", tag)
    if match is not None:
        return int(match.group(1)), int(match.group(2))

    return None


def _select_vendor_site_packages(
    vendor_dir: Path,
    python_version: tuple[int, int] | None = None,
) -> Path:
    major, minor = python_version or (sys.version_info.major, sys.version_info.minor)
    versioned = vendor_dir / f"site-packages-py{major}{minor}"
    if versioned.exists():
        return versioned
    return vendor_dir / "site-packages"
