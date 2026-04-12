from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .translation import QCoreApplication


class PreviewSource(str, Enum):
    FILE = "file"
    ARCHIVE = "archive"

    @property
    def label(self) -> str:
        if self is PreviewSource.FILE:
            return QCoreApplication.translate("PreviewSource", "Loose file")
        return QCoreApplication.translate("PreviewSource", "Archive entry")


class AudioKind(str, Enum):
    WAV = "wav"
    XWM = "xwm"
    OGG = "ogg"
    WMA = "wma"
    MP3 = "mp3"
    FLAC = "flac"
    AAC = "aac"
    MP4 = "mp4"
    UNKNOWN = "bin"


@dataclass(frozen=True)
class AudioSignature:
    kind: AudioKind
    label: str
    export_extension: str
    av_hints: tuple[str | None, ...]


@dataclass(frozen=True)
class FuzPayload:
    file_name: str
    source: PreviewSource
    version: int
    lip_data: bytes
    audio_data: bytes
    audio_signature: AudioSignature
    container_label: str = "FUZ"
    parse_notes: tuple[str, ...] = ()

    @property
    def lip_size(self) -> int:
        return len(self.lip_data)

    @property
    def audio_size(self) -> int:
        return len(self.audio_data)

    @property
    def has_lip(self) -> bool:
        return self.lip_size > 0

    @property
    def audio_export_extension(self) -> str:
        return self.audio_signature.export_extension

    def metadata_lines(self) -> list[str]:
        lines = [
            QCoreApplication.translate("FuzPayload", "File: {file_name}").format(file_name=self.file_name),
            QCoreApplication.translate("FuzPayload", "Source: {source_label}").format(source_label=self.source.label),
            QCoreApplication.translate("FuzPayload", "LIP present: {value}").format(
                value=QCoreApplication.translate("FuzPayload", "yes")
                if self.has_lip
                else QCoreApplication.translate("FuzPayload", "no")
            ),
            QCoreApplication.translate("FuzPayload", "LIP size: {size} bytes").format(size=self.lip_size),
            QCoreApplication.translate("FuzPayload", "Embedded audio: {label}").format(label=self.audio_signature.label),
            QCoreApplication.translate("FuzPayload", "Embedded audio size: {size} bytes").format(size=self.audio_size),
        ]
        if self.container_label in {"FUZ", "FUZE"}:
            lines.insert(
                2,
                QCoreApplication.translate("FuzPayload", "{container_label} version: {version}").format(
                    container_label=self.container_label,
                    version=self.version,
                ),
            )
        else:
            lines.insert(
                2,
                QCoreApplication.translate("FuzPayload", "Container: {container_label}").format(
                    container_label=self.container_label
                ),
            )
        lines.extend(
            QCoreApplication.translate("FuzPayload", "Parse note: {note}").format(note=note) for note in self.parse_notes
        )
        return lines


@dataclass(frozen=True)
class DecodeResult:
    success: bool
    error: str | None = None
    wav_data: bytes | None = None
    duration_ms: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    backend_name: str | None = None

    @classmethod
    def ok(
        cls,
        *,
        wav_data: bytes,
        duration_ms: int,
        sample_rate: int,
        channels: int,
        backend_name: str,
    ) -> "DecodeResult":
        return cls(
            success=True,
            wav_data=wav_data,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            channels=channels,
            backend_name=backend_name,
        )

    @classmethod
    def failed(cls, error: str, *, backend_name: str | None = None) -> "DecodeResult":
        return cls(success=False, error=error, backend_name=backend_name)


@dataclass
class PreviewSettings:
    autoplay: bool = True
    default_volume: int = 80
    debug_logging: bool = False


@dataclass
class PreviewState:
    status_text: str = field(
        default_factory=lambda: QCoreApplication.translate("PreviewState", "Waiting to decode audio.")
    )
    is_ready: bool = False
    is_loading: bool = False
    is_playing: bool = False
    has_error: bool = False
    duration_ms: int = 0
    position_ms: int = 0
    volume: int = 80
    can_play: bool = False
    can_export_audio: bool = False
    can_export_lip: bool = False
    error_text: str | None = None
    metadata_lines: list[str] = field(default_factory=list)
