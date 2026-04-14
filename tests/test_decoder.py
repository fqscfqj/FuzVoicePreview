from __future__ import annotations

import io
import wave

from FuzVoicePreview.decoder import AudioDecoder, _frame_to_pcm_bytes
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
        self.calls = 0

    def decode(self, payload: FuzPayload) -> DecodeResult:
        self.calls += 1
        if payload.audio_signature.kind is not self.handled_kind:
            return DecodeResult.failed("signature not handled", backend_name=self.name)
        return DecodeResult.ok(
            wav_data=build_wav_bytes(),
            duration_ms=100,
            sample_rate=22050,
            channels=1,
            backend_name=self.name,
        )


class FakeFormat:
    def __init__(self, *, is_planar: bool, sample_width: int = 2):
        self.is_planar = is_planar
        self.bytes = sample_width
        self.bits = sample_width * 8


class FakeFrame:
    def __init__(self, *, planes: list[bytes], samples: int, channels: int, is_planar: bool):
        self.planes = planes
        self.samples = samples
        self.format = FakeFormat(is_planar=is_planar)
        self.layout = type("Layout", (), {"nb_channels": channels})()


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


def test_decoder_caches_repeated_results_for_same_payload():
    payload = build_payload(OGG_SIGNATURE, b"OggSpayload")
    backend = FakeBackend(AudioKind.OGG)
    decoder = AudioDecoder(backends=[backend])

    first = decoder.decode_payload(payload)
    second = decoder.decode_payload(payload)

    assert first.success is True
    assert second.success is True
    assert backend.calls == 1


def test_frame_to_pcm_bytes_strips_packed_padding():
    frame = FakeFrame(
        planes=[b"\x01\x00\x02\x00\x03\x00\x04\x00PADPAD"],
        samples=2,
        channels=2,
        is_planar=False,
    )

    pcm = _frame_to_pcm_bytes(frame)

    assert pcm == b"\x01\x00\x02\x00\x03\x00\x04\x00"


def test_frame_to_pcm_bytes_interleaves_planar_audio():
    frame = FakeFrame(
        planes=[b"\x01\x00\x03\x00junk", b"\x02\x00\x04\x00junk"],
        samples=2,
        channels=2,
        is_planar=True,
    )

    pcm = _frame_to_pcm_bytes(frame)

    assert pcm == b"\x01\x00\x02\x00\x03\x00\x04\x00"
