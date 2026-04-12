from __future__ import annotations

from typing import Callable, Protocol

from .models import DecodeResult, FuzPayload, PreviewSettings, PreviewState


class PlayerAdapter(Protocol):
    def load(self, wav_data: bytes) -> None:
        ...

    def play(self) -> None:
        ...

    def pause(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def set_volume(self, volume: int) -> None:
        ...

    def close(self) -> None:
        ...


def format_milliseconds(value: int) -> str:
    total_seconds = max(0, int(value // 1000))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class PreviewController:
    def __init__(
        self,
        *,
        payload: FuzPayload,
        player: PlayerAdapter,
        settings: PreviewSettings,
        on_setting_changed: Callable[[str, object], None] | None = None,
    ):
        self.payload = payload
        self.player = player
        self.settings = settings
        self.on_setting_changed = on_setting_changed
        self.state = PreviewState(
            status_text="Waiting to decode audio.",
            volume=_clamp_volume(settings.default_volume),
            can_export_audio=True,
            can_export_lip=payload.has_lip,
            metadata_lines=payload.metadata_lines(),
        )

    def mark_loading(self) -> PreviewState:
        self.state.is_loading = True
        self.state.status_text = "Decoding embedded audio..."
        self.state.has_error = False
        self.state.error_text = None
        return self.state

    def apply_decode_result(self, result: DecodeResult) -> PreviewState:
        self.state.is_loading = False
        self.state.position_ms = 0
        if not result.success or not result.wav_data:
            self.state.is_ready = False
            self.state.is_playing = False
            self.state.can_play = False
            self.state.has_error = True
            self.state.error_text = result.error or "Unable to decode embedded audio."
            self.state.status_text = self.state.error_text
            return self.state

        self.player.load(result.wav_data)
        self.player.set_volume(self.state.volume)
        self.state.is_ready = True
        self.state.has_error = False
        self.state.error_text = None
        self.state.can_play = True
        self.state.duration_ms = result.duration_ms or 0
        backend = result.backend_name or "decoder"
        self.state.status_text = f"Ready to play ({backend})."

        if self.settings.autoplay:
            self.player.play()
            self.state.is_playing = True
            self.state.status_text = f"Playing ({backend})."
        else:
            self.state.is_playing = False

        return self.state

    def toggle_play_pause(self) -> PreviewState:
        if not self.state.can_play:
            return self.state
        if self.state.is_playing:
            self.player.pause()
            self.state.is_playing = False
            self.state.status_text = "Paused."
        else:
            self.player.play()
            self.state.is_playing = True
            self.state.status_text = "Playing."
        return self.state

    def stop(self) -> PreviewState:
        if not self.state.can_play:
            return self.state
        self.player.stop()
        self.state.is_playing = False
        self.state.position_ms = 0
        self.state.status_text = "Stopped."
        return self.state

    def update_position(self, position_ms: int, duration_ms: int | None = None) -> PreviewState:
        self.state.position_ms = max(0, int(position_ms))
        if duration_ms is not None:
            self.state.duration_ms = max(0, int(duration_ms))
        return self.state

    def set_volume(self, volume: int) -> PreviewState:
        clamped = _clamp_volume(volume)
        self.state.volume = clamped
        self.settings.default_volume = clamped
        self.player.set_volume(clamped)
        if self.on_setting_changed is not None:
            self.on_setting_changed("default_volume", clamped)
        return self.state

    def close(self) -> None:
        self.player.close()

    def current_time_label(self) -> str:
        return f"{format_milliseconds(self.state.position_ms)} / {format_milliseconds(self.state.duration_ms)}"


def _clamp_volume(volume: int) -> int:
    return max(0, min(100, int(volume)))
