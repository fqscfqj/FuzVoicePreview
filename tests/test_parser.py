from __future__ import annotations

import pytest

from FuzVoicePreview.models import PreviewSource
from FuzVoicePreview.parser import FUZ_MAGIC, FUZ_HEADER, FUZE_HEADER, FUZE_MAGIC, FuzFormatError, parse_fuz_bytes


def build_fuz(*, lip: bytes = b"", audio: bytes = b"RIFF\x10\x00\x00\x00WAVEdata") -> bytes:
    return FUZ_HEADER.pack(FUZ_MAGIC, 1, len(lip)) + lip + audio


def build_fuze(*, lip: bytes = b"", audio: bytes = b"RIFF\x10\x00\x00\x00WAVEdata") -> bytes:
    return FUZE_HEADER.pack(FUZE_MAGIC, 1, len(lip)) + lip + audio


def test_parse_fuz_with_lip_and_wave_audio():
    payload = parse_fuz_bytes(
        build_fuz(lip=b"LIP!", audio=b"RIFF\x10\x00\x00\x00WAVEdata"),
        file_name="voice.fuz",
        source=PreviewSource.FILE,
    )

    assert payload.file_name == "voice.fuz"
    assert payload.source is PreviewSource.FILE
    assert payload.version == 1
    assert payload.lip_data == b"LIP!"
    assert payload.audio_signature.label == "RIFF/WAVE"
    assert payload.audio_export_extension == ".wav"


def test_parse_fuz_without_lip_from_archive():
    payload = parse_fuz_bytes(
        build_fuz(lip=b"", audio=b"OggSpayload"),
        file_name="archive/voice.fuz",
        source=PreviewSource.ARCHIVE,
    )

    assert payload.source is PreviewSource.ARCHIVE
    assert payload.has_lip is False
    assert payload.audio_signature.label == "Ogg/Opus"
    assert payload.audio_export_extension == ".ogg"


def test_parse_fuz_rejects_truncated_header():
    with pytest.raises(FuzFormatError, match="truncated"):
        parse_fuz_bytes(b"FUZ", file_name="bad.fuz", source=PreviewSource.FILE)


def test_parse_fuz_rejects_truncated_lip_block():
    bad = FUZ_HEADER.pack(FUZ_MAGIC, 1, 5) + b"1234"
    with pytest.raises(FuzFormatError, match="lip block is truncated"):
        parse_fuz_bytes(bad, file_name="bad.fuz", source=PreviewSource.FILE)


def test_parse_fuz_rejects_missing_audio():
    with pytest.raises(FuzFormatError, match="embedded audio"):
        parse_fuz_bytes(
            FUZ_HEADER.pack(FUZ_MAGIC, 1, 0),
            file_name="empty.fuz",
            source=PreviewSource.FILE,
        )


def test_parse_fuz_marks_unknown_audio_payload():
    payload = parse_fuz_bytes(
        build_fuz(audio=b"\x01\x02\x03\x04payload"),
        file_name="mystery.fuz",
        source=PreviewSource.FILE,
    )

    assert payload.audio_signature.label == "Unknown"
    assert payload.audio_export_extension == ".bin"


def test_parse_fuz_accepts_raw_wave_fallback():
    payload = parse_fuz_bytes(
        b"RIFF\x10\x00\x00\x00WAVEdata",
        file_name="raw.fuz",
        source=PreviewSource.FILE,
    )

    assert payload.audio_signature.label == "RIFF/WAVE"
    assert payload.container_label == "Raw audio fallback"
    assert payload.version == 0
    assert payload.has_lip is False
    assert payload.parse_notes


def test_parse_fuze_with_lip_and_wave_audio():
    payload = parse_fuz_bytes(
        build_fuze(lip=b"LIP!", audio=b"RIFF\x10\x00\x00\x00WAVEdata"),
        file_name="voice.fuz",
        source=PreviewSource.FILE,
    )

    assert payload.container_label == "FUZE"
    assert payload.version == 1
    assert payload.lip_data == b"LIP!"
    assert payload.audio_signature.label == "RIFF/WAVE"
    assert payload.parse_notes == ()


def test_parse_fuz_accepts_unknown_raw_fallback_for_nonstandard_file():
    payload = parse_fuz_bytes(
        b"NOTFUZpayload",
        file_name="odd.fuz",
        source=PreviewSource.FILE,
    )

    assert payload.container_label == "Raw audio fallback"
    assert payload.audio_signature.label == "Unknown"
    assert "could not be identified" in payload.parse_notes[0]
