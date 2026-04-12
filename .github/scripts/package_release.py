from __future__ import annotations

import argparse
import fnmatch
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_EXCLUDES = (
    "*__pycache__*",
    "*.pyc",
    "*.pyo",
)
RUNTIME_DLL_PATTERNS = ("python3.dll", "vcruntime140*.dll")
RUNTIME_SEARCH_DIRS = (
    Path(sys.base_prefix),
    Path(sys.base_prefix) / "DLLs",
    Path(sys.exec_prefix),
    Path(sys.exec_prefix) / "DLLs",
    Path(sys.executable).resolve().parent,
    Path(sys.executable).resolve().parent / "DLLs",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the release package for FUZ Voice Preview.")
    parser.add_argument("--version", required=True, help="Release tag or version string used in archive names.")
    parser.add_argument(
        "--repo-root",
        default=str(DEFAULT_REPO_ROOT),
        help="Repository root directory. Defaults to the project root.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts",
        help="Directory where the generated zip file will be written.",
    )
    return parser.parse_args()


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    cleaned = cleaned.strip("-._")
    return cleaned or "release"


def matches_any(relative_path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in patterns)


def iter_files(root: Path, patterns: tuple[str, ...]):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        relative_path = path.relative_to(root).as_posix()
        if matches_any(relative_path, patterns):
            continue

        yield path, relative_path


def write_zip(root: Path, archive_path: Path, *, arcname_root: str, exclude_patterns: tuple[str, ...]) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        archive_path.unlink()

    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path, relative_path in iter_files(root, exclude_patterns):
            archive.write(file_path, f"{arcname_root}/{relative_path}")


def copy_tree(source_root: Path, destination_root: Path, *, exclude_patterns: tuple[str, ...]) -> None:
    for file_path, relative_path in iter_files(source_root, exclude_patterns):
        target_path = destination_root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, target_path)


def validate_bundled_runtime(repo_root: Path) -> None:
    site_packages = repo_root / "FuzVoicePreview" / "vendor" / "site-packages"
    av_package = site_packages / "av"
    av_libs = site_packages / "av.libs"

    if not av_package.exists() or not av_libs.exists():
        raise SystemExit("PyAV was not installed into FuzVoicePreview/vendor/site-packages before packaging.")


def locate_runtime_dlls() -> list[Path]:
    candidates: list[Path] = []
    for search_root in RUNTIME_SEARCH_DIRS:
        if not search_root.exists():
            continue
        for pattern in RUNTIME_DLL_PATTERNS:
            candidates.extend(sorted(search_root.glob(pattern)))

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        normalized = candidate.resolve(strict=False)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(candidate)
    return unique


def stage_release_tree(repo_root: Path, version_name: str, temp_root: Path) -> Path:
    release_stage_root = temp_root / f"FuzVoicePreview-release-{version_name}"
    plugin_stage_root = release_stage_root / "FuzVoicePreview"
    plugin_stage_root.mkdir(parents=True, exist_ok=True)

    copy_tree(
        repo_root / "FuzVoicePreview",
        plugin_stage_root,
        exclude_patterns=RELEASE_EXCLUDES,
    )

    shutil.copy2(repo_root / "README.md", release_stage_root / "README.md")

    vendor_bin_dir = plugin_stage_root / "vendor" / "bin"
    vendor_bin_dir.mkdir(parents=True, exist_ok=True)
    runtime_dlls = locate_runtime_dlls()
    if not runtime_dlls:
        raise SystemExit("Required Python runtime DLLs were not found on the runner.")
    for runtime_dll in runtime_dlls:
        shutil.copy2(runtime_dll, vendor_bin_dir / runtime_dll.name)

    return release_stage_root


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    version_name = safe_name(args.version)

    if not (repo_root / "FuzVoicePreview").is_dir():
        raise SystemExit(f"FuzVoicePreview directory was not found under {repo_root}")

    validate_bundled_runtime(repo_root)

    release_archive = output_dir / f"FuzVoicePreview-release-{version_name}.zip"

    with tempfile.TemporaryDirectory(prefix="fuz-release-") as temp_dir:
        release_stage_root = stage_release_tree(repo_root, version_name, Path(temp_dir))
        write_zip(
            release_stage_root,
            release_archive,
            arcname_root=release_stage_root.name,
            exclude_patterns=RELEASE_EXCLUDES,
        )

    print(f"Created release archive: {release_archive}")


if __name__ == "__main__":
    main()