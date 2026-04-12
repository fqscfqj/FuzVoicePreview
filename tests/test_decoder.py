from __future__ import annotations

import io
import wave

from FuzVoicePreview.decoder import AudioDecoder
from FuzVoicePreview.models import AudioKind, DecodeResult, FuzPayload, PreviewSource
from FuzVoicePreview.parser import OGG_SIGNATURE, UNKNOWN_SIGNATURE, WAV_SIGNATURE, XWM_SIGNATURE


def build_payload(signature, audio_data: bytes) -> FuzPayload:
    return FuzPayload(
        file_name="voice.fuz",
        source=PreviewSource.FILE,
        version=1,
        lip_data=b"",
        audio_data=audio_data,
        audio_signature=signature,
    )


def build_wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 16)
    return output.getvalue()


class FakeBackend:
    name = "fake"

    def __init__(self, handled_kind: AudioKind):
        self.handled_kind = handled_kind

    def decode(self, payload: FuzPayload) -> DecodeResult:
        if payload.audio_signature.kind is not self.handled_kind:
            return DecodeResult.failed("signature not handled", backend_name=self.name)
        return DecodeResult.ok(
            wav_data=build_wav_bytes(),
            duration_ms=100,
            sample_rate=22050,
            channels=1,
            backend_name=self.name,
        )


def test_decoder_uses_backend_for_xwma_payload():
    payload = build_payload(XWM_SIGNATURE, b"RIFF\x10\x00\x00\x00XWMAdata")
    decoder = AudioDecoder(backends=[FakeBackend(AudioKind.XWM)])

    result = decoder.decode_payload(payload)

    assert result.success is True
    assert result.backend_name == "fake"
    assert result.wav_data is not None


def test_decoder_handles_unknown_payload_gracefully():
    payload = build_payload(UNKNOWN_SIGNATURE, b"\x00\x01\x02")
    decoder = AudioDecoder(backends=[])

    result = decoder.decode_payload(payload)

    assert result.success is False
    assert result.error == "No audio decoder backend available."


def test_decoder_reports_missing_backend_for_wave_payload():
    payload = build_payload(WAV_SIGNATURE, b"RIFF\x10\x00\x00\x00WAVEdata")
    decoder = AudioDecoder(backends=[])

    result = decoder.decode_payload(payload)

    assert result.success is False
    assert result.error == "No audio decoder backend available."


def test_decoder_can_passthrough_valid_wave_payload_without_pyav():
    payload = build_payload(WAV_SIGNATURE, build_wav_bytes())
    decoder = AudioDecoder()

    result = decoder.decode_payload(payload)

    assert result.success is True
    assert result.backend_name == "wave"
    assert result.wav_data == payload.audio_data
    assert result.duration_ms == 0


def test_decoder_can_route_ogg_payload_to_backend():
    payload = build_payload(OGG_SIGNATURE, b"OggSpayload")
    decoder = AudioDecoder(backends=[FakeBackend(AudioKind.OGG)])

    result = decoder.decode_payload(payload)

    assert result.success is True
    assert result.channels == 1
