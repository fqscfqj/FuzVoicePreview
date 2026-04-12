from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PreviewSource(str, Enum):
    FILE = "file"
    ARCHIVE = "archive"

    @property
    def label(self) -> str:
        if self is PreviewSource.FILE:
            return "Loose file"
        return "Archive entry"


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
            f"File: {self.file_name}",
            f"Source: {self.source.label}",
            f"LIP present: {'yes' if self.has_lip else 'no'}",
            f"LIP size: {self.lip_size} bytes",
            f"Embedded audio: {self.audio_signature.label}",
            f"Embedded audio size: {self.audio_size} bytes",
        ]
        if self.container_label in {"FUZ", "FUZE"}:
            lines.insert(2, f"{self.container_label} version: {self.version}")
        else:
            lines.insert(2, f"Container: {self.container_label}")
        lines.extend(f"Parse note: {note}" for note in self.parse_notes)
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
    status_text: str = "Waiting to decode audio."
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
