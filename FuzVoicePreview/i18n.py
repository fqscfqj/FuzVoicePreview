from __future__ import annotations

from pathlib import Path

from .translation import QCoreApplication as QCoreApplication
from .translation import _candidate_translation_paths as _translation_candidate_translation_paths
from .translation import _normalize_language_tag as _normalize_language_tag


def _candidate_translation_paths(base_name: str, plugin_dir: Path, ui_languages: list[str]) -> list[Path]:
    return _translation_candidate_translation_paths(base_name, [plugin_dir], ui_languages)


__all__ = ["QCoreApplication", "_candidate_translation_paths", "_normalize_language_tag"]
