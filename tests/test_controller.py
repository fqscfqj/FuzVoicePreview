from __future__ import annotations

from FuzVoicePreview.controller import PreviewController, format_milliseconds
from FuzVoicePreview.models import DecodeResult, FuzPayload, PreviewSettings, PreviewSource
from FuzVoicePreview.parser import WAV_SIGNATURE


class FakePlayer:
    def __init__(self):
        self.calls: list[tuple[str, object | None]] = []

    def load(self, wav_data: bytes) -> None:
        self.calls.append(("load", wav_data))

    def play(self) -> None:
        self.calls.append(("play", None))

    def pause(self) -> None:
        self.calls.append(("pause", None))

    def stop(self) -> None:
        self.calls.append(("stop", None))

    def set_volume(self, volume: int) -> None:
        self.calls.append(("set_volume", volume))

    def close(self) -> None:
        self.calls.append(("close", None))


def build_payload() -> FuzPayload:
    return FuzPayload(
        file_name="voice.fuz",
        source=PreviewSource.FILE,
        version=1,
        lip_data=b"LIP!",
        audio_data=b"RIFF\x10\x00\x00\x00WAVEdata",
        audio_signature=WAV_SIGNATURE,
    )


def test_controller_autoplay_starts_playback_after_decode():
    player = FakePlayer()
    controller = PreviewController(
        payload=build_payload(),
        player=player,
        settings=PreviewSettings(autoplay=True, default_volume=80),
    )

    controller.mark_loading()
    state = controller.apply_decode_result(
        DecodeResult.ok(
            wav_data=b"wav",
            duration_ms=2500,
            sample_rate=22050,
            channels=1,
            backend_name="fake",
        )
    )

    assert state.is_ready is True
    assert state.is_playing is True
    assert ("load", b"wav") in player.calls
    assert ("play", None) in player.calls


def test_controller_can_skip_autoplay_when_decode_finishes_in_inactive_view():
    player = FakePlayer()
    controller = PreviewController(
        payload=build_payload(),
        player=player,
        settings=PreviewSettings(autoplay=True, default_volume=80),
    )

    state = controller.apply_decode_result(
        DecodeResult.ok(
            wav_data=b"wav",
            duration_ms=2500,
            sample_rate=22050,
            channels=1,
            backend_name="fake",
        ),
        autoplay=False,
    )

    assert state.is_ready is True
    assert state.is_playing is False
    assert ("load", b"wav") in player.calls
    assert ("play", None) not in player.calls


def test_controller_toggle_pause_and_resume():
    player = FakePlayer()
    controller = PreviewController(
        payload=build_payload(),
        player=player,
        settings=PreviewSettings(autoplay=False, default_volume=50),
    )
    controller.apply_decode_result(
        DecodeResult.ok(
            wav_data=b"wav",
            duration_ms=1000,
            sample_rate=22050,
            channels=1,
            backend_name="fake",
        )
    )

    controller.toggle_play_pause()
    controller.toggle_play_pause()

    assert ("play", None) in player.calls
    assert ("pause", None) in player.calls


def test_controller_updates_volume_and_persists_setting():
    player = FakePlayer()
    changed: list[tuple[str, object]] = []
    controller = PreviewController(
        payload=build_payload(),
        player=player,
        settings=PreviewSettings(autoplay=False, default_volume=50),
        on_setting_changed=lambda key, value: changed.append((key, value)),
    )

    controller.set_volume(135)

    assert controller.state.volume == 100
    assert ("set_volume", 100) in player.calls
    assert ("default_volume", 100) in changed


def test_controller_handles_decode_failure_without_crashing():
    player = FakePlayer()
    controller = PreviewController(
        payload=build_payload(),
        player=player,
        settings=PreviewSettings(),
    )

    state = controller.apply_decode_result(DecodeResult.failed("decoder failed"))

    assert state.can_play is False
    assert state.has_error is True
    assert state.error_text == "decoder failed"


def test_controller_closes_player():
    player = FakePlayer()
    controller = PreviewController(
        payload=build_payload(),
        player=player,
        settings=PreviewSettings(),
    )

    controller.close()

    assert player.calls[-1] == ("close", None)


def test_time_formatting_is_stable():
    assert format_milliseconds(65_000) == "1:05"
    assert format_milliseconds(3_725_000) == "1:02:05"
