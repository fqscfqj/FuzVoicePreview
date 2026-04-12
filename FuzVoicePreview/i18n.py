from __future__ import annotations

from pathlib import Path

try:  # pragma: no cover - exercised only inside MO2 / PyQt6 runtime
    from PyQt6.QtCore import QCoreApplication as _QtCoreApplication
    from PyQt6.QtCore import QLocale, QTranslator

    _TRANSLATOR: QTranslator | None = None
    _TRANSLATION_ATTEMPTED = False

    def _normalize_language_tag(tag: str) -> list[str]:
        cleaned = tag.replace("-", "_").strip()
        if not cleaned:
            return []

        parts = [part for part in cleaned.split("_") if part]
        variants: list[str] = []
        for length in range(len(parts), 0, -1):
            variants.append("_".join(parts[:length]))
        return variants

    def _candidate_translation_paths(base_name: str, plugin_dir: Path, ui_languages: list[str]) -> list[Path]:
        candidates: list[Path] = []
        seen: set[Path] = set()
        for language in ui_languages:
            for variant in _normalize_language_tag(language):
                path = plugin_dir / f"{base_name}_{variant}.qm"
                if path in seen:
                    continue
                seen.add(path)
                candidates.append(path)
        return candidates

    def _install_translator() -> None:
        global _TRANSLATOR, _TRANSLATION_ATTEMPTED

        if _TRANSLATOR is not None or _TRANSLATION_ATTEMPTED:
            return

        app = _QtCoreApplication.instance()
        if app is None:
            return

        _TRANSLATION_ATTEMPTED = True
        plugin_dir = Path(__file__).resolve().parent
        base_name = plugin_dir.name
        translator = QTranslator(app)

        ui_languages = []
        locale = QLocale()
        if hasattr(locale, "uiLanguages"):
            ui_languages.extend(locale.uiLanguages())
        locale_name = locale.name()
        if locale_name:
            ui_languages.append(locale_name)

        for candidate in _candidate_translation_paths(base_name, plugin_dir, ui_languages):
            if not candidate.exists():
                continue
            if translator.load(str(candidate)):
                app.installTranslator(translator)
                _TRANSLATOR = translator
                return

        # Fall back to Qt's locale-based filename resolution if the manual match missed.
        if translator.load(locale, base_name, "_", str(plugin_dir)):
            app.installTranslator(translator)
            _TRANSLATOR = translator
            return

    class QCoreApplication:  # type: ignore[no-redef]
        @staticmethod
        def translate(context: str, source_text: str, disambiguation: str | None = None, n: int = -1) -> str:
            _install_translator()
            return _QtCoreApplication.translate(context, source_text, disambiguation, n)
except Exception:  # pragma: no cover - local test environment does not ship PyQt6
    class QCoreApplication:  # type: ignore[no-redef]
        @staticmethod
        def translate(context: str, source_text: str, disambiguation: str | None = None, n: int = -1) -> str:
            return source_text


    def _normalize_language_tag(tag: str) -> list[str]:
        cleaned = tag.replace("-", "_").strip()
        if not cleaned:
            return []

        parts = [part for part in cleaned.split("_") if part]
        variants: list[str] = []
        for length in range(len(parts), 0, -1):
            variants.append("_".join(parts[:length]))
        return variants


    def _candidate_translation_paths(base_name: str, plugin_dir: Path, ui_languages: list[str]) -> list[Path]:
        candidates: list[Path] = []
        seen: set[Path] = set()
        for language in ui_languages:
            for variant in _normalize_language_tag(language):
                path = plugin_dir / f"{base_name}_{variant}.qm"
                if path in seen:
                    continue
                seen.add(path)
                candidates.append(path)
        return candidates
