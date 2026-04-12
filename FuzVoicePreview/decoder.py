from __future__ import annotations

import importlib
import io
import wave
from dataclasses import dataclass
from typing import Protocol

from .models import AudioKind, DecodeResult, FuzPayload


class DecoderBackend(Protocol):
    name: str

    def decode(self, payload: FuzPayload) -> DecodeResult:
        ...


class UnsupportedAudioError(RuntimeError):
    pass


@dataclass
class PyAvAudioBackend:
    name: str = "PyAV"

    def decode(self, payload: FuzPayload) -> DecodeResult:
        av = self._load_av()
        if av is None:
            return DecodeResult.failed("PyAV is not available.", backend_name=self.name)

        last_error: str | None = None
        hints = payload.audio_signature.av_hints if payload.audio_signature.kind is not AudioKind.UNKNOWN else (None,)
        for hint in _dedupe_hints(hints):
            try:
                return self._decode_with_hint(av, payload, hint)
            except Exception as exc:  # pragma: no cover - exercised only with PyAV installed
                label = hint or "autodetect"
                last_error = f"{label}: {exc}"

        return DecodeResult.failed(
            f"PyAV could not decode the embedded audio payload ({last_error or 'no matching demuxer'}).",
            backend_name=self.name,
        )

    def _load_av(self):
        try:
            return importlib.import_module("av")
        except Exception:
            return None

    def _decode_with_hint(self, av, payload: FuzPayload, hint: str | None) -> DecodeResult:
        container = av.open(io.BytesIO(payload.audio_data), mode="r", format=hint)
        try:
            audio_stream = next(stream for stream in container.streams if stream.type == "audio")
        except StopIteration as exc:
            container.close()
            raise UnsupportedAudioError("No audio stream found in embedded payload.") from exc

        rate = _first_non_none(
            getattr(audio_stream, "rate", None),
            getattr(getattr(audio_stream, "codec_context", None), "sample_rate", None),
            44100,
        )
        layout = _extract_layout_name(audio_stream) or "stereo"
        resampler = av.audio.resampler.AudioResampler(format="s16", layout=layout, rate=rate)

        pcm_chunks: list[bytes] = []
        sample_rate: int | None = None
        channels: int | None = None

        for packet in container.demux(audio_stream):
            for frame in packet.decode():
                resampled_frames = resampler.resample(frame)
                if resampled_frames is None:
                    continue
                if not isinstance(resampled_frames, list):
                    resampled_frames = [resampled_frames]
                for resampled in resampled_frames:
                    sample_rate = sample_rate or _first_non_none(
                        getattr(resampled, "sample_rate", None),
                        rate,
                    )
                    channels = channels or _extract_channel_count(resampled) or 2
                    pcm_chunks.append(_frame_to_pcm_bytes(resampled))

        container.close()

        if not pcm_chunks or not sample_rate or not channels:
            raise UnsupportedAudioError("Decoded audio stream did not yield PCM frames.")

        pcm_data = b"".join(pcm_chunks)
        wav_data = _pcm_to_wav(pcm_data, sample_rate=sample_rate, channels=channels)
        duration_ms = int(len(pcm_data) / (channels * 2) * 1000 / sample_rate)
        return DecodeResult.ok(
            wav_data=wav_data,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            channels=channels,
            backend_name=self.name,
        )


@dataclass
class WaveStdlibBackend:
    name: str = "wave"

    def decode(self, payload: FuzPayload) -> DecodeResult:
        if payload.audio_signature.kind is not AudioKind.WAV:
            raise UnsupportedAudioError("Only RIFF/WAVE payloads are supported by the stdlib backend.")

        try:
            with wave.open(io.BytesIO(payload.audio_data), "rb") as wav_file:
                channels = max(1, wav_file.getnchannels())
                sample_rate = max(1, wav_file.getframerate())
                frame_count = max(0, wav_file.getnframes())
        except wave.Error as exc:
            raise UnsupportedAudioError(f"Invalid RIFF/WAVE payload: {exc}") from exc

        duration_ms = int(frame_count * 1000 / sample_rate)
        return DecodeResult.ok(
            wav_data=payload.audio_data,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            channels=channels,
            backend_name=self.name,
        )


class AudioDecoder:
    def __init__(self, backends: list[DecoderBackend] | None = None):
        self._backends = list(backends) if backends is not None else [WaveStdlibBackend(), PyAvAudioBackend()]

    def decode_payload(self, payload: FuzPayload) -> DecodeResult:
        errors: list[str] = []
        available = False
        for backend in self._backends:
            available = True
            try:
                result = backend.decode(payload)
            except UnsupportedAudioError as exc:
                errors.append(f"{backend.name}: {exc}")
                continue
            except Exception as exc:
                errors.append(f"{backend.name}: {exc}")
                continue

            if result.success:
                return result
            if result.error:
                errors.append(f"{backend.name}: {result.error}")

        if not available:
            return DecodeResult.failed("No audio decoder backend available.")

        return DecodeResult.failed(
            "Unable to decode embedded audio. " + "; ".join(errors) if errors else "Unable to decode embedded audio."
        )


def _dedupe_hints(hints: tuple[str | None, ...]) -> list[str | None]:
    seen: set[str | None] = set()
    ordered: list[str | None] = []
    for hint in hints:
        if hint in seen:
            continue
        ordered.append(hint)
        seen.add(hint)
    return ordered


def _extract_layout_name(stream_or_frame) -> str | None:
    layout = getattr(stream_or_frame, "layout", None)
    if layout is None:
        return None
    name = getattr(layout, "name", None)
    if name:
        return str(name)
    channels = getattr(layout, "channels", None)
    if channels:
        try:
            return "mono" if len(channels) == 1 else "stereo"
        except TypeError:
            return None
    return None


def _extract_channel_count(frame) -> int | None:
    layout = getattr(frame, "layout", None)
    if layout is not None:
        count = getattr(layout, "nb_channels", None)
        if count:
            return int(count)
        channels = getattr(layout, "channels", None)
        if channels:
            try:
                return len(channels)
            except TypeError:
                pass
    return None


def _frame_to_pcm_bytes(frame) -> bytes:
    try:
        plane = frame.planes[0]
        return bytes(plane)
    except Exception:
        pass

    array = frame.to_ndarray()  # pragma: no cover - requires PyAV + numpy
    if getattr(array, "ndim", 1) == 1:
        return array.astype("<i2", copy=False).tobytes()
    return array.transpose().astype("<i2", copy=False).tobytes()


def _pcm_to_wav(pcm_data: bytes, *, sample_rate: int, channels: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return output.getvalue()


def _first_non_none(*values):
    for value in values:
        if value is not None:
            return value
    return None
