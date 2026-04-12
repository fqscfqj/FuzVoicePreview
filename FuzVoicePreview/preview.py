from __future__ import annotations

import pathlib
from typing import Callable

from .controller import PreviewController
from .decoder import AudioDecoder
from .i18n import QCoreApplication
from .models import DecodeResult, FuzPayload, PreviewSettings
from .playback import MCI_AVAILABLE, MciPlaybackSnapshot, MciWavePlayerCore

try:  # pragma: no cover - exercised only inside MO2 / PyQt6 runtime
    from PyQt6.QtCore import (
        QByteArray,
        QBuffer,
        QIODevice,
        QObject,
        QSignalBlocker,
        QThread,
        QTimer,
        Qt,
        pyqtSignal,
    )
    from PyQt6.QtWidgets import (
        QFileDialog,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QSlider,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    BASIC_QT_AVAILABLE = True
    BASIC_QT_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - local test environment does not ship PyQt6
    BASIC_QT_AVAILABLE = False
    BASIC_QT_IMPORT_ERROR = exc

try:  # pragma: no cover - exercised only inside MO2 / PyQt6 runtime
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

    MULTIMEDIA_AVAILABLE = True
    MULTIMEDIA_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - local test environment does not ship PyQt6
    MULTIMEDIA_AVAILABLE = False
    MULTIMEDIA_IMPORT_ERROR = exc


if BASIC_QT_AVAILABLE:  # pragma: no cover - exercised only inside MO2 / PyQt6 runtime
    class DecodeWorker(QObject):
        finished = pyqtSignal(object)

        def __init__(self, payload: FuzPayload, decoder: AudioDecoder):
            super().__init__()
            self._payload = payload
            self._decoder = decoder

        def run(self) -> None:
            result = self._decoder.decode_payload(self._payload)
            self.finished.emit(result)


    class NullMediaPlayerAdapter(QObject):
        supports_seek = False
        supports_volume = False
        position_changed = pyqtSignal(int)
        duration_changed = pyqtSignal(int)
        playback_changed = pyqtSignal(bool)
        error_changed = pyqtSignal(str)

        def load(self, wav_data: bytes) -> None:
            self.error_changed.emit(QCoreApplication.translate("NullMediaPlayerAdapter", "No playback backend is available."))

        def play(self) -> None:
            self.error_changed.emit(QCoreApplication.translate("NullMediaPlayerAdapter", "No playback backend is available."))

        def pause(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def set_volume(self, volume: int) -> None:
            return None

        def set_position(self, position_ms: int) -> None:
            return None

        def close(self) -> None:
            return None


    if MULTIMEDIA_AVAILABLE:
        class QtMediaPlayerAdapter(QObject):
            supports_seek = True
            supports_volume = True
            position_changed = pyqtSignal(int)
            duration_changed = pyqtSignal(int)
            playback_changed = pyqtSignal(bool)
            error_changed = pyqtSignal(str)

            def __init__(self, parent: QWidget | None = None):
                super().__init__(parent)
                self._player = QMediaPlayer(parent)
                self._audio_output = QAudioOutput(parent)
                self._player.setAudioOutput(self._audio_output)
                self._buffer: QBuffer | None = None
                self._payload_bytes: QByteArray | None = None

                self._player.positionChanged.connect(self.position_changed.emit)
                self._player.durationChanged.connect(self.duration_changed.emit)
                self._player.playbackStateChanged.connect(self._on_playback_state_changed)
                self._player.errorOccurred.connect(self._on_error)

            def load(self, wav_data: bytes) -> None:
                self._payload_bytes = QByteArray(wav_data)
                self._buffer = QBuffer(self)
                self._buffer.setData(self._payload_bytes)
                self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
                self._player.setSourceDevice(self._buffer)

            def play(self) -> None:
                self._player.play()

            def pause(self) -> None:
                self._player.pause()

            def stop(self) -> None:
                self._player.stop()

            def set_volume(self, volume: int) -> None:
                self._audio_output.setVolume(max(0.0, min(1.0, volume / 100.0)))

            def set_position(self, position_ms: int) -> None:
                self._player.setPosition(position_ms)

            def close(self) -> None:
                self._player.stop()
                if self._buffer is not None:
                    self._buffer.close()
                self._buffer = None
                self._payload_bytes = None

            def _on_playback_state_changed(self, state) -> None:
                self.playback_changed.emit(state == QMediaPlayer.PlaybackState.PlayingState)

            def _on_error(self, _error, error_string: str) -> None:
                if error_string:
                    self.error_changed.emit(error_string)

        PlayerAdapterClass = QtMediaPlayerAdapter
    elif MCI_AVAILABLE:
        class MciWavePlayerAdapter(QObject):
            supports_seek = True
            supports_volume = True
            position_changed = pyqtSignal(int)
            duration_changed = pyqtSignal(int)
            playback_changed = pyqtSignal(bool)
            error_changed = pyqtSignal(str)

            def __init__(self, parent: QWidget | None = None):
                super().__init__(parent)
                self._player = MciWavePlayerCore()
                self._snapshot = MciPlaybackSnapshot(position_ms=0, duration_ms=0, is_playing=False)
                self._timer = QTimer(self)
                self._timer.setInterval(200)
                self._timer.timeout.connect(self._on_tick)

            def load(self, wav_data: bytes) -> None:
                try:
                    self._player.load(wav_data)
                except Exception as exc:
                    self.error_changed.emit(str(exc))
                    return
                self._timer.stop()
                self._publish_snapshot(self._player.poll(), force_duration=True, force_position=True, force_playback=True)

            def play(self) -> None:
                try:
                    self._player.play()
                except Exception as exc:
                    self.error_changed.emit(str(exc))
                    return
                self._timer.start()
                self._publish_snapshot(self._player.poll(), force_playback=True)

            def pause(self) -> None:
                try:
                    self._player.pause()
                except Exception as exc:
                    self.error_changed.emit(str(exc))
                    return
                self._timer.stop()
                self._publish_snapshot(self._player.poll(), force_playback=True, force_position=True)

            def stop(self) -> None:
                try:
                    self._player.stop()
                except Exception as exc:
                    self.error_changed.emit(str(exc))
                    return
                self._timer.stop()
                self._publish_snapshot(self._player.poll(), force_playback=True, force_position=True)

            def set_volume(self, volume: int) -> None:
                try:
                    self._player.set_volume(volume)
                except Exception as exc:
                    self.error_changed.emit(str(exc))
                    return
                self._publish_snapshot(self._player.poll(), force_duration=True, force_position=True)

            def set_position(self, position_ms: int) -> None:
                try:
                    self._player.set_position(position_ms)
                except Exception as exc:
                    self.error_changed.emit(str(exc))
                    return
                self._publish_snapshot(self._player.poll(), force_position=True)

            def close(self) -> None:
                self._timer.stop()
                self._player.close()
                self._snapshot = MciPlaybackSnapshot(position_ms=0, duration_ms=0, is_playing=False)

            def _on_tick(self) -> None:
                try:
                    snapshot = self._player.poll()
                except Exception as exc:
                    self._timer.stop()
                    self.error_changed.emit(str(exc))
                    return
                self._publish_snapshot(snapshot)
                if not snapshot.is_playing:
                    self._timer.stop()

            def _publish_snapshot(
                self,
                snapshot: MciPlaybackSnapshot,
                *,
                force_duration: bool = False,
                force_position: bool = False,
                force_playback: bool = False,
            ) -> None:
                previous = self._snapshot
                self._snapshot = snapshot
                if force_duration or snapshot.duration_ms != previous.duration_ms:
                    self.duration_changed.emit(snapshot.duration_ms)
                if force_position or snapshot.position_ms != previous.position_ms:
                    self.position_changed.emit(snapshot.position_ms)
                if force_playback or snapshot.is_playing != previous.is_playing:
                    self.playback_changed.emit(snapshot.is_playing)

        PlayerAdapterClass = MciWavePlayerAdapter
    else:
        PlayerAdapterClass = NullMediaPlayerAdapter
    PLAYBACK_AVAILABLE = MULTIMEDIA_AVAILABLE or MCI_AVAILABLE


    class FuzPreviewWidget(QWidget):
        def __init__(
            self,
            *,
            payload: FuzPayload,
            decoder: AudioDecoder,
            settings: PreviewSettings,
            set_setting: Callable[[str, object], None],
            diagnostics: tuple[str, ...],
        ):
            super().__init__()
            self._payload = payload
            self._settings = settings
            self._set_setting = set_setting
            self._diagnostics = diagnostics
            self._player = PlayerAdapterClass(self)
            self._controller = PreviewController(
                payload=payload,
                player=self._player,
                settings=settings,
                on_setting_changed=set_setting,
            )
            self._decoder = decoder
            self._decode_thread: QThread | None = None
            self._decode_worker: DecodeWorker | None = None

            self._metadata = QTextEdit()
            self._metadata.setReadOnly(True)
            self._metadata.setMinimumHeight(140)

            self._status = QLabel()
            self._status.setWordWrap(True)
            self._status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

            self._play_button = QPushButton(QCoreApplication.translate("FuzPreviewWidget", "Play"))
            self._stop_button = QPushButton(QCoreApplication.translate("FuzPreviewWidget", "Stop"))
            self._position_slider = QSlider(Qt.Orientation.Horizontal)
            self._time_label = QLabel("0:00 / 0:00")
            self._volume_slider = QSlider(Qt.Orientation.Horizontal)
            self._export_audio_button = QPushButton(QCoreApplication.translate("FuzPreviewWidget", "Export Audio"))
            self._export_lip_button = QPushButton(QCoreApplication.translate("FuzPreviewWidget", "Export LIP"))

            self._build_layout()
            self._wire_events()
            self._refresh_view()
            self._start_decode()

        def closeEvent(self, event) -> None:
            self._cleanup_worker()
            self._controller.close()
            super().closeEvent(event)

        def _build_layout(self) -> None:
            self._volume_slider.setRange(0, 100)
            self._volume_slider.setValue(self._controller.state.volume)

            controls = QGroupBox(QCoreApplication.translate("FuzPreviewWidget", "Playback"))
            controls_layout = QGridLayout()
            controls_layout.addWidget(self._play_button, 0, 0)
            controls_layout.addWidget(self._stop_button, 0, 1)
            controls_layout.addWidget(self._position_slider, 1, 0, 1, 2)
            controls_layout.addWidget(self._time_label, 1, 2)
            controls_layout.addWidget(QLabel(QCoreApplication.translate("FuzPreviewWidget", "Volume")), 2, 0)
            controls_layout.addWidget(self._volume_slider, 2, 1, 1, 2)
            controls.setLayout(controls_layout)

            exports = QHBoxLayout()
            exports.addWidget(self._export_audio_button)
            exports.addWidget(self._export_lip_button)

            root = QVBoxLayout()
            root.addWidget(QLabel(QCoreApplication.translate("FuzPreviewWidget", "FUZ metadata")))
            root.addWidget(self._metadata)
            root.addWidget(self._status)
            root.addWidget(controls)
            root.addLayout(exports)
            self.setLayout(root)

        def _wire_events(self) -> None:
            self._play_button.clicked.connect(self._toggle_playback)
            self._stop_button.clicked.connect(self._stop_playback)
            self._volume_slider.valueChanged.connect(self._change_volume)
            self._export_audio_button.clicked.connect(self._export_audio)
            self._export_lip_button.clicked.connect(self._export_lip)
            self._position_slider.sliderMoved.connect(self._seek)
            self._player.position_changed.connect(self._on_position_changed)
            self._player.duration_changed.connect(self._on_duration_changed)
            self._player.playback_changed.connect(self._on_playback_changed)
            self._player.error_changed.connect(self._on_player_error)

        def _start_decode(self) -> None:
            if not PLAYBACK_AVAILABLE:
                self._on_decode_finished(
                    DecodeResult.failed(QCoreApplication.translate("FuzPreviewWidget", "No playback backend is available."))
                )
                return

            self._controller.mark_loading()
            self._refresh_view()

            self._decode_thread = QThread(self)
            self._decode_worker = DecodeWorker(self._payload, self._decoder)
            self._decode_worker.moveToThread(self._decode_thread)
            self._decode_thread.started.connect(self._decode_worker.run)
            self._decode_worker.finished.connect(self._on_decode_finished)
            self._decode_worker.finished.connect(self._decode_thread.quit)
            self._decode_worker.finished.connect(self._decode_worker.deleteLater)
            self._decode_thread.finished.connect(self._decode_thread.deleteLater)
            self._decode_thread.start()

        def _cleanup_worker(self) -> None:
            if self._decode_thread is not None and self._decode_thread.isRunning():
                self._decode_thread.quit()
                self._decode_thread.wait(1000)
            self._decode_thread = None
            self._decode_worker = None

        def _on_decode_finished(self, result: DecodeResult) -> None:
            self._controller.apply_decode_result(result)
            self._refresh_view()
            self._cleanup_worker()

        def _on_position_changed(self, value: int) -> None:
            self._controller.update_position(value)
            with QSignalBlocker(self._position_slider):
                self._position_slider.setValue(value)
            self._time_label.setText(self._controller.current_time_label())

        def _on_duration_changed(self, value: int) -> None:
            self._controller.update_position(self._controller.state.position_ms, value)
            self._position_slider.setRange(0, max(0, value))
            self._time_label.setText(self._controller.current_time_label())

        def _on_playback_changed(self, is_playing: bool) -> None:
            self._controller.state.is_playing = is_playing
            if is_playing:
                self._controller.state.status_text = QCoreApplication.translate("FuzPreviewWidget", "Playing.")
            else:
                self._controller.state.status_text = (
                    QCoreApplication.translate("FuzPreviewWidget", "Stopped.")
                    if self._controller.state.position_ms == 0
                    else QCoreApplication.translate("FuzPreviewWidget", "Paused.")
                )
            self._refresh_view()

        def _on_player_error(self, error_text: str) -> None:
            self._controller.state.has_error = True
            self._controller.state.error_text = error_text
            self._controller.state.status_text = error_text
            self._refresh_view()

        def _toggle_playback(self) -> None:
            self._controller.toggle_play_pause()
            self._refresh_view()

        def _stop_playback(self) -> None:
            self._controller.stop()
            self._refresh_view()

        def _change_volume(self, value: int) -> None:
            self._controller.set_volume(value)
            self._refresh_view()

        def _seek(self, value: int) -> None:
            if not getattr(self._player, "supports_seek", True):
                return
            self._player.set_position(value)
            self._controller.update_position(value)
            self._time_label.setText(self._controller.current_time_label())

        def _refresh_view(self) -> None:
            state = self._controller.state
            diagnostics = list(self._diagnostics)
            if state.error_text:
                diagnostics.append(
                    QCoreApplication.translate("FuzPreviewWidget", "Decode status: {error_text}").format(
                        error_text=state.error_text
                    )
                )
            if not state.can_play and not state.is_loading and not state.error_text:
                diagnostics.append(
                    QCoreApplication.translate("FuzPreviewWidget", "Decode status: Playback is unavailable.")
                )

            self._metadata.setPlainText("\n".join(state.metadata_lines + diagnostics))
            self._status.setText(state.status_text)
            self._play_button.setEnabled(state.can_play)
            self._play_button.setText(
                QCoreApplication.translate("FuzPreviewWidget", "Pause")
                if state.is_playing
                else QCoreApplication.translate("FuzPreviewWidget", "Play")
            )
            self._stop_button.setEnabled(state.can_play)
            self._position_slider.setEnabled(state.can_play and getattr(self._player, "supports_seek", True))
            self._volume_slider.setEnabled(state.can_play and getattr(self._player, "supports_volume", True))
            self._export_audio_button.setEnabled(state.can_export_audio)
            self._export_lip_button.setEnabled(state.can_export_lip)
            self._time_label.setText(self._controller.current_time_label())

        def _export_audio(self) -> None:
            default_name = pathlib.Path(self._payload.file_name).stem + self._payload.audio_export_extension
            target, _ = QFileDialog.getSaveFileName(
                self,
                QCoreApplication.translate("FuzPreviewWidget", "Export embedded audio"),
                default_name,
            )
            if not target:
                return
            pathlib.Path(target).write_bytes(self._payload.audio_data)

        def _export_lip(self) -> None:
            default_name = pathlib.Path(self._payload.file_name).stem + ".lip"
            target, _ = QFileDialog.getSaveFileName(
                self,
                QCoreApplication.translate("FuzPreviewWidget", "Export lip data"),
                default_name,
            )
            if not target:
                return
            pathlib.Path(target).write_bytes(self._payload.lip_data)


    class ErrorPreviewWidget(QWidget):
        def __init__(self, *, title: str, lines: list[str]):
            super().__init__()
            layout = QVBoxLayout()
            heading = QLabel(title)
            heading.setWordWrap(True)
            details = QTextEdit()
            details.setReadOnly(True)
            details.setPlainText("\n".join(lines))
            layout.addWidget(heading)
            layout.addWidget(details)
            self.setLayout(layout)


def build_preview_widget(  # pragma: no cover - exercised only inside MO2 / PyQt6 runtime
    *,
    payload: FuzPayload | None,
    parse_error: str | None,
    file_name: str,
    source_label: str,
    decoder: AudioDecoder,
    settings: PreviewSettings,
    set_setting: Callable[[str, object], None],
    diagnostics: tuple[str, ...],
):
    if not BASIC_QT_AVAILABLE:
        raise RuntimeError(
            QCoreApplication.translate("build_preview_widget", "PyQt6 runtime is unavailable: {error}").format(
                error=BASIC_QT_IMPORT_ERROR
            )
        )

    lines = [
        QCoreApplication.translate("build_preview_widget", "File: {file_name}").format(file_name=file_name),
        QCoreApplication.translate("build_preview_widget", "Source: {source_label}").format(source_label=source_label),
    ]
    lines.extend(diagnostics)
    if not MULTIMEDIA_AVAILABLE:
        if MCI_AVAILABLE:
            lines.append(QCoreApplication.translate("build_preview_widget", "Playback backend: MCI fallback"))
            if settings.debug_logging:
                lines.append(
                    QCoreApplication.translate("build_preview_widget", "PyQt6.QtMultimedia: {error}").format(
                        error=MULTIMEDIA_IMPORT_ERROR
                    )
                )
        else:
            lines.append(
                QCoreApplication.translate("build_preview_widget", "PyQt6.QtMultimedia: {error}").format(
                    error=MULTIMEDIA_IMPORT_ERROR
                )
            )
            lines.append(QCoreApplication.translate("build_preview_widget", "Playback backend: unavailable"))

    if parse_error is not None:
        lines.append(QCoreApplication.translate("build_preview_widget", "Parse status: {error}").format(error=parse_error))
        return ErrorPreviewWidget(
            title=QCoreApplication.translate("build_preview_widget", "Invalid FUZ container."),
            lines=lines,
        )

    assert payload is not None
    return FuzPreviewWidget(
        payload=payload,
        decoder=decoder,
        settings=settings,
        set_setting=set_setting,
        diagnostics=tuple(lines),
    )
