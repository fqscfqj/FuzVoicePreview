from __future__ import annotations

from pathlib import Path

from . import translation as _translation

QCoreApplication = _translation.QCoreApplication
_normalize_language_tag = _translation._normalize_language_tag


def _candidate_translation_paths(base_name: str, plugin_dir: Path, ui_languages: list[str]) -> list[Path]:
    return _translation._candidate_translation_paths(base_name, [plugin_dir], ui_languages)


__all__ = ["QCoreApplication", "_candidate_translation_paths", "_normalize_language_tag"]
