from __future__ import annotations

from pathlib import Path

from .translation import QCoreApplication
from .decoder import AudioDecoder
from .models import PreviewSettings, PreviewSource
from .parser import FuzFormatError, parse_fuz_bytes
from .runtime import RuntimeDiagnostics, configure_runtime

try:  # pragma: no cover - exercised only inside MO2 runtime
    import mobase
except Exception:  # pragma: no cover - local tests do not ship mobase
    mobase = None


BasePlugin = mobase.IPluginPreview if mobase is not None else object


class FuzVoicePreviewPlugin(BasePlugin):
    def __init__(self):
        if mobase is not None:
            super().__init__()
        self._organizer = None
        self._runtime: RuntimeDiagnostics | None = None
        self._decoder = AudioDecoder()

    def init(self, organizer) -> bool:
        self._organizer = organizer
        self._runtime = configure_runtime()
        return True

    def name(self) -> str:
        return "FUZ Voice Preview"

    def localizedName(self) -> str:
        return QCoreApplication.translate("FuzVoicePreviewPlugin", "FUZ Voice Preview")

    def author(self) -> str:
        return "OpenAI"

    def description(self) -> str:
        return QCoreApplication.translate("FuzVoicePreviewPlugin", "Preview and play FUZ voice files in MO2.")

    def version(self):
        if mobase is None:
            return (1, 0, 0, 0)
        return mobase.VersionInfo(1, 0, 0, 0)

    def settings(self):
        if mobase is None:
            return []
        return [
            mobase.PluginSetting(
                "autoplay",
                QCoreApplication.translate("FuzVoicePreviewPlugin", "Start playback automatically after decode."),
                True,
            ),
            mobase.PluginSetting(
                "default_volume",
                QCoreApplication.translate("FuzVoicePreviewPlugin", "Default preview volume (0-100)."),
                80,
            ),
            mobase.PluginSetting(
                "debug_logging",
                QCoreApplication.translate(
                    "FuzVoicePreviewPlugin", "Enable extra runtime diagnostics in preview widgets."
                ),
                False,
            ),
        ]

    def supportedExtensions(self) -> set[str]:
        return {"fuz"}

    def supportsArchives(self) -> bool:
        return True

    def genFilePreview(self, fileName, maxSize):
        file_path = self._resolve_preview_path(fileName)
        return self._build_preview(
            raw_data=file_path.read_bytes(),
            file_name=Path(fileName).name or file_path.name,
            source=PreviewSource.FILE,
        )

    def genDataPreview(self, fileData, fileName, maxSize):
        return self._build_preview(
            raw_data=bytes(fileData),
            file_name=fileName,
            source=PreviewSource.ARCHIVE,
        )

    def _build_preview(self, *, raw_data: bytes, file_name: str, source: PreviewSource):
        from .preview import build_preview_widget

        payload = None
        parse_error = None
        diagnostics = list(self._diagnostic_lines())
        try:
            payload = parse_fuz_bytes(raw_data, file_name=file_name, source=source)
        except FuzFormatError as exc:
            parse_error = str(exc)
            diagnostics.append(self._header_diagnostic(raw_data))
        else:
            if payload.audio_signature.label == "Unknown" or payload.container_label != "FUZ":
                diagnostics.append(self._header_diagnostic(raw_data))
                diagnostics.append(self._embedded_audio_header_diagnostic(payload))

        return build_preview_widget(
            payload=payload,
            parse_error=parse_error,
            file_name=file_name,
            source_label=source.label,
            decoder=self._decoder,
            settings=self._load_settings(),
            set_setting=self._set_setting,
            diagnostics=tuple(diagnostics),
        )

    def _resolve_preview_path(self, file_name: str) -> Path:
        direct_path = Path(file_name)
        for candidate in self._concrete_preview_path_candidates(file_name):
            if candidate.exists():
                return candidate

        if self._organizer is not None and not direct_path.is_absolute():
            try:
                resolved = self._organizer.resolvePath(file_name)
            except Exception:
                resolved = ""
            if resolved:
                resolved_path = Path(resolved)
                if resolved_path.exists():
                    return resolved_path
        return direct_path

    def _concrete_preview_path_candidates(self, file_name: str) -> tuple[Path, ...]:
        direct_path = Path(file_name)
        if direct_path.is_absolute():
            return (direct_path,)

        normalized = file_name.replace("\\", "/").lstrip("./")
        candidates: list[Path] = [direct_path]
        if self._organizer is not None:
            for root in self._candidate_roots():
                if not normalized:
                    continue
                candidates.append(root / normalized)

        unique: list[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            normalized_candidate = candidate.resolve(strict=False)
            if normalized_candidate in seen:
                continue
            seen.add(normalized_candidate)
            unique.append(candidate)
        return tuple(unique)

    def _candidate_roots(self) -> tuple[Path, ...]:
        if self._organizer is None:
            return ()

        roots: list[Path] = []
        for getter_name in ("modsPath", "basePath"):
            getter = getattr(self._organizer, getter_name, None)
            if getter is None:
                continue
            try:
                value = getter()
            except Exception:
                continue
            if not value:
                continue
            roots.append(Path(value))

        unique: list[Path] = []
        seen: set[Path] = set()
        for root in roots:
            normalized_root = root.resolve(strict=False)
            if normalized_root in seen:
                continue
            seen.add(normalized_root)
            unique.append(root)
        return tuple(unique)

    def _load_settings(self) -> PreviewSettings:
        autoplay = self._plugin_setting("autoplay", True)
        default_volume = self._plugin_setting("default_volume", 80)
        debug_logging = self._plugin_setting("debug_logging", False)
        return PreviewSettings(
            autoplay=bool(autoplay),
            default_volume=int(default_volume),
            debug_logging=bool(debug_logging),
        )

    def _plugin_setting(self, key: str, default):
        if self._organizer is None:
            return default
        try:
            return self._organizer.pluginSetting(self.name(), key)
        except Exception:
            return default

    def _set_setting(self, key: str, value) -> None:
        if self._organizer is None:
            return
        self._organizer.setPluginSetting(self.name(), key, value)

    def _diagnostic_lines(self) -> tuple[str, ...]:
        if self._runtime is None:
            return ()
        debug_logging = bool(self._plugin_setting("debug_logging", False))
        lines = list(self._runtime.messages)
        if not debug_logging:
            prefix = QCoreApplication.translate("RuntimeDiagnostics", "{module_name}: {error}").format(
                module_name="PyQt6.QtMultimedia",
                error="",
            )
            lines = [line for line in lines if not line.startswith(prefix)]
        if debug_logging:
            lines.append(
                QCoreApplication.translate("FuzVoicePreviewPlugin", "vendor_dir: {path}").format(
                    path=self._runtime.vendor_dir
                )
            )
            lines.append(
                QCoreApplication.translate("FuzVoicePreviewPlugin", "pyav_available: {value}").format(
                    value=self._runtime.pyav_available
                )
            )
            lines.append(
                QCoreApplication.translate("FuzVoicePreviewPlugin", "qt_multimedia_available: {value}").format(
                    value=self._runtime.qt_multimedia_available
                )
            )
        return tuple(lines)

    def _header_diagnostic(self, raw_data: bytes) -> str:
        head = raw_data[:16]
        hex_head = " ".join(f"{byte:02X}" for byte in head) if head else "<empty>"
        ascii_head = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in head)
        return QCoreApplication.translate("FuzVoicePreviewPlugin", "Header bytes: {hex_head} | {ascii_head}").format(
            hex_head=hex_head,
            ascii_head=ascii_head,
        )

    def _embedded_audio_header_diagnostic(self, payload) -> str:
        head = payload.audio_data[:16]
        hex_head = " ".join(f"{byte:02X}" for byte in head) if head else "<empty>"
        ascii_head = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in head)
        return QCoreApplication.translate(
            "FuzVoicePreviewPlugin", "Embedded audio header: {hex_head} | {ascii_head}"
        ).format(
            hex_head=hex_head,
            ascii_head=ascii_head,
        )
