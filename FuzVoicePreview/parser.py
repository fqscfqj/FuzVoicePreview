from __future__ import annotations

import struct
from pathlib import Path

from .models import AudioKind, AudioSignature, FuzPayload, PreviewSource

FUZ_HEADER = struct.Struct("<4sII")
FUZ_MAGIC = b"FUZ\x00"
FUZE_HEADER = struct.Struct("<4sII")
FUZE_MAGIC = b"FUZE"


class FuzFormatError(ValueError):
    pass


WAV_SIGNATURE = AudioSignature(
    kind=AudioKind.WAV,
    label="RIFF/WAVE",
    export_extension=".wav",
    av_hints=("wav", None),
)
XWM_SIGNATURE = AudioSignature(
    kind=AudioKind.XWM,
    label="RIFF/XWMA",
    export_extension=".xwm",
    av_hints=("xwma", "wav", None),
)
OGG_SIGNATURE = AudioSignature(
    kind=AudioKind.OGG,
    label="Ogg/Opus",
    export_extension=".ogg",
    av_hints=("ogg", None),
)
WMA_SIGNATURE = AudioSignature(
    kind=AudioKind.WMA,
    label="ASF/WMA",
    export_extension=".wma",
    av_hints=("asf", None),
)
MP3_SIGNATURE = AudioSignature(
    kind=AudioKind.MP3,
    label="MP3",
    export_extension=".mp3",
    av_hints=("mp3", None),
)
FLAC_SIGNATURE = AudioSignature(
    kind=AudioKind.FLAC,
    label="FLAC",
    export_extension=".flac",
    av_hints=("flac", None),
)
AAC_SIGNATURE = AudioSignature(
    kind=AudioKind.AAC,
    label="AAC/ADTS",
    export_extension=".aac",
    av_hints=("aac", None),
)
MP4_SIGNATURE = AudioSignature(
    kind=AudioKind.MP4,
    label="MP4/M4A",
    export_extension=".m4a",
    av_hints=("mp4", None),
)
UNKNOWN_SIGNATURE = AudioSignature(
    kind=AudioKind.UNKNOWN,
    label="Unknown",
    export_extension=".bin",
    av_hints=(None,),
)


def parse_fuz_file(file_name: str) -> FuzPayload:
    file_path = Path(file_name)
    return parse_fuz_bytes(
        file_path.read_bytes(),
        file_name=file_path.name,
        source=PreviewSource.FILE,
    )


def parse_fuz_bytes(data: bytes, *, file_name: str, source: PreviewSource) -> FuzPayload:
    raw_audio_signature = detect_audio_signature(data)

    if len(data) < FUZ_HEADER.size:
        if raw_audio_signature.kind is not AudioKind.UNKNOWN:
            return _build_raw_audio_payload(
                file_name=file_name,
                source=source,
                audio_data=data,
                audio_signature=raw_audio_signature,
            )
        raise FuzFormatError(
            f"FUZ header is truncated: expected at least {FUZ_HEADER.size} bytes, got {len(data)}."
        )

    if len(data) >= FUZE_HEADER.size and data.startswith(FUZE_MAGIC):
        return _parse_fuze_bytes(data, file_name=file_name, source=source)

    magic, version, lip_size = FUZ_HEADER.unpack_from(data, 0)
    if magic != FUZ_MAGIC:
        return _build_raw_audio_payload(
            file_name=file_name,
            source=source,
            audio_data=data,
            audio_signature=raw_audio_signature,
        )

    lip_offset = FUZ_HEADER.size
    audio_offset = lip_offset + lip_size
    if audio_offset > len(data):
        raise FuzFormatError(
            f"FUZ lip block is truncated: header declares {lip_size} bytes but file only has {len(data) - lip_offset}."
        )

    lip_data = data[lip_offset:audio_offset]
    audio_data = data[audio_offset:]
    if not audio_data:
        raise FuzFormatError("FUZ payload does not contain embedded audio data.")

    return FuzPayload(
        file_name=file_name,
        source=source,
        version=version,
        lip_data=lip_data,
        audio_data=audio_data,
        audio_signature=detect_audio_signature(audio_data),
    )


def _parse_fuze_bytes(data: bytes, *, file_name: str, source: PreviewSource) -> FuzPayload:
    if len(data) < FUZE_HEADER.size:
        raise FuzFormatError(
            f"FUZE header is truncated: expected at least {FUZE_HEADER.size} bytes, got {len(data)}."
        )

    magic, version, lip_size = FUZE_HEADER.unpack_from(data, 0)
    if magic != FUZE_MAGIC:
        raise FuzFormatError("Invalid FUZE header magic; expected 'FUZE'.")

    lip_offset = FUZE_HEADER.size
    audio_offset = lip_offset + lip_size
    if audio_offset > len(data):
        raise FuzFormatError(
            f"FUZE lip block is truncated: header declares {lip_size} bytes but file only has {len(data) - lip_offset}."
        )

    lip_data = data[lip_offset:audio_offset]
    audio_data = data[audio_offset:]
    if not audio_data:
        raise FuzFormatError("FUZE payload does not contain embedded audio data.")

    return FuzPayload(
        file_name=file_name,
        source=source,
        version=version,
        lip_data=lip_data,
        audio_data=audio_data,
        audio_signature=detect_audio_signature(audio_data),
        container_label="FUZE",
    )


def detect_audio_signature(audio_data: bytes) -> AudioSignature:
    if audio_data.startswith(b"RIFF") and len(audio_data) >= 12:
        riff_kind = audio_data[8:12]
        if riff_kind == b"WAVE":
            return WAV_SIGNATURE
        if riff_kind.upper() == b"XWMA":
            return XWM_SIGNATURE
    if audio_data.startswith(b"OggS"):
        return OGG_SIGNATURE
    if audio_data.startswith(b"\x30\x26\xB2\x75\x8E\x66\xCF\x11\xA6\xD9\x00\xAA\x00\x62\xCE\x6C"):
        return WMA_SIGNATURE
    if audio_data.startswith(b"ID3") or _looks_like_mp3_frame(audio_data):
        return MP3_SIGNATURE
    if audio_data.startswith(b"fLaC"):
        return FLAC_SIGNATURE
    if _looks_like_aac_adts(audio_data):
        return AAC_SIGNATURE
    if len(audio_data) >= 8 and audio_data[4:8] == b"ftyp":
        return MP4_SIGNATURE
    return UNKNOWN_SIGNATURE


def _build_raw_audio_payload(
    *,
    file_name: str,
    source: PreviewSource,
    audio_data: bytes,
    audio_signature: AudioSignature,
) -> FuzPayload:
    note = "File does not start with a standard FUZ header; treating the whole file as embedded audio."
    if audio_signature.kind is AudioKind.UNKNOWN:
        note = (
            "File does not start with a standard FUZ header and the audio format could not be identified from its signature."
        )
    return FuzPayload(
        file_name=file_name,
        source=source,
        version=0,
        lip_data=b"",
        audio_data=audio_data,
        audio_signature=audio_signature,
        container_label="Raw audio fallback",
        parse_notes=(note,),
    )


def _looks_like_mp3_frame(data: bytes) -> bool:
    return len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0


def _looks_like_aac_adts(data: bytes) -> bool:
    return len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xF6) == 0xF0
