from __future__ import annotations

import io
import wave
from pathlib import Path

from FuzVoicePreview.i18n import _candidate_translation_paths, _normalize_language_tag
from FuzVoicePreview.playback import (
    ExclusivePlaybackCoordinator,
    MciWavePlayerCore,
    _scale_pcm_frames,
    scale_wav_volume,
)
from FuzVoicePreview.plugin import FuzVoicePreviewPlugin


def build_wav_bytes(*, sample_width: int, samples: list[int], channels: int = 1, sample_rate: int = 22050) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(encode_samples(samples, sample_width))
    return output.getvalue()


def encode_samples(samples: list[int], sample_width: int) -> bytes:
    output = bytearray()
    for sample in samples:
        if sample_width == 1:
            output.append(sample + 128)
        elif sample_width == 3:
            output.extend(int(sample).to_bytes(4, byteorder="little", signed=True)[:3])
        else:
            output.extend(int(sample).to_bytes(sample_width, byteorder="little", signed=True))
    return bytes(output)


def decode_samples(frame_data: bytes, sample_width: int) -> list[int]:
    samples: list[int] = []
    for offset in range(0, len(frame_data), sample_width):
        chunk = frame_data[offset : offset + sample_width]
        if sample_width == 1:
            samples.append(chunk[0] - 128)
        elif sample_width == 3:
            sign_extension = b"\xff" if chunk[2] & 0x80 else b"\x00"
            samples.append(int.from_bytes(chunk + sign_extension, byteorder="little", signed=True))
        else:
            samples.append(int.from_bytes(chunk, byteorder="little", signed=True))
    return samples


class FakeMciTransport:
    def __init__(self, *, duration_ms: int = 1000):
        self.duration_ms = duration_ms
        self.position_ms = 0
        self.mode = "stopped"
        self.commands: list[str] = []

    def send(self, command: str) -> str:
        self.commands.append(command)
        if command.startswith("open "):
            self.mode = "stopped"
            self.position_ms = 0
            return "1"
        if command.startswith("set "):
            return ""
        if command.endswith(" length"):
            return str(self.duration_ms)
        if command.endswith(" position"):
            return str(self.position_ms)
        if command.endswith(" mode"):
            return self.mode
        if "seek " in command and " to start" in command:
            self.position_ms = 0
            self.mode = "stopped"
            return ""
        if "seek " in command and " to " in command:
            self.position_ms = int(command.rsplit(" ", 1)[-1])
            self.mode = "stopped"
            return ""
        if "play " in command and " from " in command:
            self.position_ms = int(command.rsplit(" ", 1)[-1])
            self.mode = "playing"
            return ""
        if command.startswith("pause "):
            self.mode = "paused"
            return ""
        if command.startswith("stop "):
            self.mode = "stopped"
            return ""
        if command.startswith("close "):
            self.mode = "stopped"
            return ""
        raise AssertionError(f"Unexpected MCI command: {command}")


class FakeExclusivePlayer:
    def __init__(self, name: str):
        self.name = name
        self.pause_calls = 0

    def pause(self) -> None:
        self.pause_calls += 1


def test_scale_wav_volume_passthrough_at_full_volume():
    wav_data = build_wav_bytes(sample_width=2, samples=[1000, -1000, 500])

    assert scale_wav_volume(wav_data, 100) == wav_data


def test_scale_wav_volume_mutes_unsigned_8bit_pcm():
    wav_data = build_wav_bytes(sample_width=1, samples=[-128, 0, 127])

    scaled = scale_wav_volume(wav_data, 0)

    with wave.open(io.BytesIO(scaled), "rb") as wav_file:
        assert wav_file.readframes(wav_file.getnframes()) == b"\x80\x80\x80"


def test_pcm_gain_clips_16bit_samples():
    scaled = _scale_pcm_frames(encode_samples([30_000, -30_000], 2), sample_width=2, volume=200)

    assert decode_samples(scaled, 2) == [32_767, -32_768]


def test_scale_wav_volume_scales_24bit_pcm():
    wav_data = build_wav_bytes(sample_width=3, samples=[1_000_000, -1_000_000, 500_000])

    scaled = scale_wav_volume(wav_data, 50)

    with wave.open(io.BytesIO(scaled), "rb") as wav_file:
        frames = wav_file.readframes(wav_file.getnframes())
    assert decode_samples(frames, 3) == [500_000, -500_000, 250_000]


def test_scale_wav_volume_preserves_wav_header_parameters():
    wav_data = build_wav_bytes(sample_width=4, samples=[200_000, -200_000], channels=2, sample_rate=44100)

    scaled = scale_wav_volume(wav_data, 50)

    with wave.open(io.BytesIO(wav_data), "rb") as original, wave.open(io.BytesIO(scaled), "rb") as updated:
        assert updated.getparams() == original.getparams()


def test_mci_wave_player_core_preserves_position_and_playback_state_during_volume_rebuild():
    transport = FakeMciTransport(duration_ms=2000)
    written_payloads: list[bytes] = []

    def temp_writer(wav_data: bytes) -> Path:
        written_payloads.append(wav_data)
        return Path(f"fake-{len(written_payloads)}.wav")

    player = MciWavePlayerCore(transport=transport, temp_writer=temp_writer, alias="preview_alias")
    player.load(build_wav_bytes(sample_width=2, samples=[1000] * 32))
    player.play()
    player.set_position(750)

    player.set_volume(25)
    snapshot = player.poll()

    assert player.supports_seek is True
    assert player.supports_volume is True
    assert len(written_payloads) == 2
    assert transport.position_ms == 750
    assert transport.mode == "playing"
    assert snapshot.position_ms == 750
    assert snapshot.is_playing is True


def test_exclusive_playback_coordinator_pauses_previous_player():
    coordinator = ExclusivePlaybackCoordinator()
    first = FakeExclusivePlayer("first")
    second = FakeExclusivePlayer("second")

    coordinator.activate(first)
    coordinator.activate(second)

    assert first.pause_calls == 1
    assert second.pause_calls == 0


def test_exclusive_playback_coordinator_ignores_repeated_activation_and_release():
    coordinator = ExclusivePlaybackCoordinator()
    player = FakeExclusivePlayer("only")

    coordinator.activate(player)
    coordinator.activate(player)
    coordinator.release(player)
    coordinator.activate(player)

    assert player.pause_calls == 0


def test_plugin_translation_methods_do_not_require_pyqt6_runtime():
    plugin = FuzVoicePreviewPlugin()

    assert plugin.localizedName() == "FUZ Voice Preview"
    assert plugin.description() == "Preview and play FUZ voice files in MO2."


def test_normalize_language_tag_generates_progressive_fallbacks():
    assert _normalize_language_tag("zh-Hans-CN") == ["zh_Hans_CN", "zh_Hans", "zh"]
    assert _normalize_language_tag("zh_CN") == ["zh_CN", "zh"]


def test_candidate_translation_paths_prefers_specific_locale_then_fallback():
    plugin_dir = Path("plugin-dir")

    candidates = _candidate_translation_paths("FuzVoicePreview", plugin_dir, ["zh-Hans-CN", "en-US"])

    assert candidates[:5] == [
        plugin_dir / "FuzVoicePreview_zh_Hans_CN.qm",
        plugin_dir / "FuzVoicePreview_zh_Hans.qm",
        plugin_dir / "FuzVoicePreview_zh.qm",
        plugin_dir / "FuzVoicePreview_en_US.qm",
        plugin_dir / "FuzVoicePreview_en.qm",
    ]
