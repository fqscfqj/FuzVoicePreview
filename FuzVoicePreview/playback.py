from __future__ import annotations

import ctypes
import os
import tempfile
import wave
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable, Protocol


try:  # pragma: no cover - Windows only
    _WINMM = ctypes.WinDLL("winmm")
except Exception:  # pragma: no cover - non-Windows or missing DLL
    _WINMM = None


MCI_AVAILABLE = os.name == "nt" and _WINMM is not None


class ExclusivePlaybackPlayer(Protocol):
    def pause(self) -> None:
        ...


class ExclusivePlaybackCoordinator:
    def __init__(self):
        self._active_player: ExclusivePlaybackPlayer | None = None

    def activate(self, player: ExclusivePlaybackPlayer) -> None:
        previous = self._active_player
        if previous is player:
            return

        self._active_player = player
        if previous is None:
            return

        try:
            previous.pause()
        except Exception:
            return

    def release(self, player: ExclusivePlaybackPlayer) -> None:
        if self._active_player is player:
            self._active_player = None


PLAYBACK_COORDINATOR = ExclusivePlaybackCoordinator()


@dataclass(frozen=True)
class MciPlaybackSnapshot:
    position_ms: int
    duration_ms: int
    is_playing: bool


class MciCommandError(RuntimeError):
    def __init__(self, command: str, error_code: int, message: str):
        super().__init__(f"{message} ({command})")
        self.command = command
        self.error_code = error_code
        self.message = message


class WinmmMciTransport:
    def __init__(self):
        if _WINMM is None:
            raise RuntimeError("Windows MCI playback is unavailable.")

    def send(self, command: str) -> str:
        buffer = ctypes.create_unicode_buffer(255)
        error_code = _WINMM.mciSendStringW(command, buffer, len(buffer), 0)
        if error_code:
            message = self._error_message(error_code)
            raise MciCommandError(command, error_code, message)
        return buffer.value

    def _error_message(self, error_code: int) -> str:
        buffer = ctypes.create_unicode_buffer(255)
        if _WINMM is not None and _WINMM.mciGetErrorStringW(error_code, buffer, len(buffer)):
            return buffer.value
        return f"MCI error {error_code}"


class MciWavePlayerCore:
    supports_seek = True
    supports_volume = True

    def __init__(
        self,
        *,
        transport: WinmmMciTransport | None = None,
        temp_writer: Callable[[bytes], Path] | None = None,
        alias: str | None = None,
    ):
        self._transport = transport or WinmmMciTransport()
        self._temp_writer = temp_writer or _write_temp_wav
        self._alias = alias or f"fuzpreview_{os.getpid()}_{id(self):x}"
        self._source_wav_data: bytes | None = None
        self._temp_file: Path | None = None
        self._duration_ms = 0
        self._position_ms = 0
        self._is_playing = False
        self._volume = 100

    @property
    def duration_ms(self) -> int:
        return self._duration_ms

    @property
    def position_ms(self) -> int:
        return self._position_ms

    @property
    def volume(self) -> int:
        return self._volume

    def load(self, wav_data: bytes) -> None:
        self._source_wav_data = wav_data
        self._rebuild_media(position_ms=0, is_playing=False)

    def play(self) -> None:
        self._require_media()
        start_position = self._query_position_ms()
        self._send(f"play {self._alias} from {start_position}")
        self._position_ms = start_position
        self._is_playing = True

    def pause(self) -> None:
        if self._source_wav_data is None:
            return
        self._position_ms = self._query_position_ms()
        self._send(f"pause {self._alias}")
        self._is_playing = False

    def stop(self) -> None:
        if self._source_wav_data is None:
            return
        self._send(f"stop {self._alias}")
        self._send(f"seek {self._alias} to start")
        self._position_ms = 0
        self._is_playing = False

    def set_position(self, position_ms: int) -> None:
        if self._source_wav_data is None:
            return
        target = max(0, min(self._duration_ms, int(position_ms)))
        if self._is_playing:
            self._send(f"play {self._alias} from {target}")
        else:
            self._send(f"seek {self._alias} to {target}")
        self._position_ms = target

    def set_volume(self, volume: int) -> None:
        clamped = max(0, min(100, int(volume)))
        if self._source_wav_data is None:
            self._volume = clamped
            return
        current_position = self._query_position_ms()
        self._volume = clamped
        self._rebuild_media(position_ms=current_position, is_playing=self._is_playing)

    def poll(self) -> MciPlaybackSnapshot:
        if self._source_wav_data is None:
            return MciPlaybackSnapshot(position_ms=self._position_ms, duration_ms=self._duration_ms, is_playing=False)

        self._position_ms = self._query_position_ms()
        self._is_playing = self._query_mode() == "playing"
        return MciPlaybackSnapshot(
            position_ms=self._position_ms,
            duration_ms=self._duration_ms,
            is_playing=self._is_playing,
        )

    def close(self) -> None:
        self._close_media()
        self._source_wav_data = None
        self._duration_ms = 0
        self._position_ms = 0
        self._is_playing = False

    def _rebuild_media(self, *, position_ms: int, is_playing: bool) -> None:
        self._require_media()
        scaled_wav = scale_wav_volume(self._source_wav_data, self._volume)
        self._close_media()
        self._temp_file = self._temp_writer(scaled_wav)
        self._send(f'open "{self._temp_file}" type waveaudio alias {self._alias}')
        self._send(f"set {self._alias} time format milliseconds")
        self._duration_ms = self._query_int(f"status {self._alias} length")
        self._position_ms = max(0, min(self._duration_ms, int(position_ms)))
        self._is_playing = False
        if self._position_ms:
            self._send(f"seek {self._alias} to {self._position_ms}")
        if is_playing:
            self._send(f"play {self._alias} from {self._position_ms}")
            self._is_playing = True

    def _close_media(self) -> None:
        try:
            self._send(f"close {self._alias}")
        except Exception:
            pass
        if self._temp_file is not None:
            try:
                self._temp_file.unlink(missing_ok=True)
            except OSError:
                pass
        self._temp_file = None

    def _query_mode(self) -> str:
        return self._send(f"status {self._alias} mode").strip().lower()

    def _query_position_ms(self) -> int:
        return max(0, min(self._duration_ms, self._query_int(f"status {self._alias} position")))

    def _query_int(self, command: str) -> int:
        value = self._send(command).strip()
        return int(value or "0")

    def _require_media(self) -> None:
        if self._source_wav_data is None:
            raise RuntimeError("No decoded WAV payload is loaded.")

    def _send(self, command: str) -> str:
        return self._transport.send(command)


def scale_wav_volume(wav_data: bytes, volume: int) -> bytes:
    clamped = max(0, min(100, int(volume)))
    if clamped == 100:
        return wav_data

    with wave.open(BytesIO(wav_data), "rb") as reader:
        params = reader.getparams()
        if reader.getcomptype() != "NONE":
            raise ValueError("Only PCM WAV data can be scaled in the MCI fallback backend.")
        sample_width = reader.getsampwidth()
        frame_data = reader.readframes(reader.getnframes())

    scaled_frames = _scale_pcm_frames(frame_data, sample_width=sample_width, volume=clamped)

    output = BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setparams(params)
        writer.writeframes(scaled_frames)
    return output.getvalue()


def soften_wav_start(wav_data: bytes, *, fade_in_ms: int = 8) -> bytes:
    if fade_in_ms <= 0:
        return wav_data

    try:
        with wave.open(BytesIO(wav_data), "rb") as reader:
            params = reader.getparams()
            if reader.getcomptype() != "NONE":
                return wav_data
            sample_width = reader.getsampwidth()
            channels = max(1, reader.getnchannels())
            sample_rate = max(1, reader.getframerate())
            frame_count = max(0, reader.getnframes())
            frame_data = reader.readframes(frame_count)
    except (wave.Error, EOFError):
        return wav_data

    if frame_count == 0 or sample_width not in {1, 2, 3, 4}:
        return wav_data

    fade_frames = min(frame_count, max(1, round(sample_rate * fade_in_ms / 1000)))
    if fade_frames <= 1:
        return wav_data

    frame_size = channels * sample_width
    softened = bytearray(frame_data)
    for frame_index in range(fade_frames):
        factor = frame_index / fade_frames
        frame_offset = frame_index * frame_size
        for channel_index in range(channels):
            offset = frame_offset + channel_index * sample_width
            sample = _decode_pcm_sample(frame_data[offset : offset + sample_width], sample_width)
            faded = _clamp_pcm_sample(round(sample * factor), sample_width)
            softened[offset : offset + sample_width] = _encode_pcm_sample(faded, sample_width)

    output = BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setparams(params)
        writer.writeframes(bytes(softened))
    return output.getvalue()


def _scale_pcm_frames(frame_data: bytes, *, sample_width: int, volume: int) -> bytes:
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError(f"Unsupported PCM sample width: {sample_width}")
    if volume == 100:
        return frame_data
    if volume == 0:
        fill_byte = 0x80 if sample_width == 1 else 0x00
        return bytes([fill_byte]) * len(frame_data)

    factor = volume / 100.0
    output = bytearray(len(frame_data))
    for offset in range(0, len(frame_data), sample_width):
        sample = _decode_pcm_sample(frame_data[offset : offset + sample_width], sample_width)
        scaled = _clamp_pcm_sample(round(sample * factor), sample_width)
        output[offset : offset + sample_width] = _encode_pcm_sample(scaled, sample_width)
    return bytes(output)


def _decode_pcm_sample(data: bytes, sample_width: int) -> int:
    if sample_width == 1:
        return data[0] - 128
    if sample_width == 3:
        sign_extension = b"\xff" if data[2] & 0x80 else b"\x00"
        return int.from_bytes(data + sign_extension, byteorder="little", signed=True)
    return int.from_bytes(data, byteorder="little", signed=True)


def _encode_pcm_sample(sample: int, sample_width: int) -> bytes:
    if sample_width == 1:
        return bytes([sample + 128])
    if sample_width == 3:
        return int(sample).to_bytes(4, byteorder="little", signed=True)[:3]
    return int(sample).to_bytes(sample_width, byteorder="little", signed=True)


def _clamp_pcm_sample(sample: int, sample_width: int) -> int:
    if sample_width == 1:
        return max(-128, min(127, sample))
    max_value = (1 << (sample_width * 8 - 1)) - 1
    min_value = -(1 << (sample_width * 8 - 1))
    return max(min_value, min(max_value, sample))


def _write_temp_wav(wav_data: bytes) -> Path:
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    try:
        temp_file.write(wav_data)
    finally:
        temp_file.close()
    return Path(temp_file.name)
