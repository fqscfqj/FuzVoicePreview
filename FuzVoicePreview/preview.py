from __future__ import annotations

import pathlib
from typing import Callable

from .controller import PreviewController
from .decoder import AudioDecoder
from .i18n import QCoreApplication
from .models import DecodeResult, FuzPayload, PreviewSettings
from .playback import MCI_AVAILABLE, PLAYBACK_COORDINATOR, MciPlaybackSnapshot, MciWavePlayerCore

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
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QSizePolicy,
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
                PLAYBACK_COORDINATOR.activate(self)
                self._player.play()

            def pause(self) -> None:
                self._player.pause()
                PLAYBACK_COORDINATOR.release(self)

            def stop(self) -> None:
                self._player.stop()
                PLAYBACK_COORDINATOR.release(self)

            def set_volume(self, volume: int) -> None:
                self._audio_output.setVolume(max(0.0, min(1.0, volume / 100.0)))

            def set_position(self, position_ms: int) -> None:
                self._player.setPosition(position_ms)

            def close(self) -> None:
                self._player.stop()
                PLAYBACK_COORDINATOR.release(self)
                if self._buffer is not None:
                    self._buffer.close()
                self._buffer = None
                self._payload_bytes = None

            def _on_playback_state_changed(self, state) -> None:
                if state != QMediaPlayer.PlaybackState.PlayingState:
                    PLAYBACK_COORDINATOR.release(self)
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
                    PLAYBACK_COORDINATOR.activate(self)
                    self._player.play()
                except Exception as exc:
                    PLAYBACK_COORDINATOR.release(self)
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
                PLAYBACK_COORDINATOR.release(self)
                self._publish_snapshot(self._player.poll(), force_playback=True, force_position=True)

            def stop(self) -> None:
                try:
                    self._player.stop()
                except Exception as exc:
                    self.error_changed.emit(str(exc))
                    return
                self._timer.stop()
                PLAYBACK_COORDINATOR.release(self)
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
                PLAYBACK_COORDINATOR.release(self)
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
                if not snapshot.is_playing:
                    PLAYBACK_COORDINATOR.release(self)
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


    def _preview_stylesheet() -> str:
        return """
        QWidget#PreviewRoot {
            background-color: #f4efe7;
            color: #2d2a26;
            font-family: "Segoe UI";
        }
        QFrame#StatusCard,
        QFrame#InfoCard,
        QGroupBox#PlaybackGroup {
            background-color: #fffaf2;
            border: 1px solid #dbcbb7;
            border-radius: 14px;
        }
        QGroupBox#PlaybackGroup {
            margin-top: 12px;
            padding-top: 10px;
        }
        QGroupBox#PlaybackGroup::title {
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 6px;
            color: #6d5a44;
            font-weight: 600;
        }
        QLabel#StatusTitle {
            font-size: 15px;
            font-weight: 600;
        }
        QLabel#StatusHint {
            color: #6f6255;
            font-size: 12px;
        }
        QLabel#SummaryItem {
            background-color: #f7efe2;
            border: 1px solid #eadcca;
            border-radius: 10px;
            padding: 8px 10px;
            color: #43382c;
        }
        QPushButton {
            background-color: #f7efe2;
            color: #3c3228;
            border: 1px solid #cfbda5;
            border-radius: 10px;
            padding: 8px 14px;
        }
        QPushButton:hover {
            background-color: #f1e4d1;
        }
        QPushButton:pressed {
            background-color: #e8d6bb;
        }
        QPushButton:disabled {
            background-color: #ece5dc;
            color: #a49788;
            border-color: #ddd2c6;
        }
        QPushButton#PrimaryButton {
            background-color: #2f6f65;
            color: #ffffff;
            border-color: #2b6259;
            font-weight: 600;
        }
        QPushButton#PrimaryButton:hover {
            background-color: #387e72;
        }
        QPushButton#PrimaryButton:pressed {
            background-color: #285b53;
        }
        QPushButton#DangerButton {
            background-color: #fbf1eb;
            color: #7d4331;
            border-color: #dfbca8;
            font-weight: 600;
        }
        QPushButton#DangerButton:hover {
            background-color: #f8e6dc;
        }
        QPushButton#ExportButton {
            font-weight: 600;
        }
        QPushButton#DetailsToggle {
            background-color: transparent;
            border: none;
            color: #5e4c39;
            padding: 2px 0;
            text-align: left;
            font-weight: 600;
        }
        QPushButton#DetailsToggle:hover {
            color: #2f6f65;
        }
        QLabel#TimeBadge {
            background-color: #efe5d6;
            border: 1px solid #d7c4aa;
            border-radius: 10px;
            padding: 6px 10px;
            color: #614f3c;
            font-weight: 600;
        }
        QLabel#VolumeValue {
            color: #6a5b4b;
            font-weight: 600;
            min-width: 40px;
        }
        QTextEdit#DetailsText {
            background-color: #fcf7f1;
            border: 1px solid #eadcca;
            border-radius: 10px;
            padding: 4px;
            selection-background-color: #d9c3a0;
        }
        QSlider::groove:horizontal {
            height: 6px;
            background: #d8cabb;
            border-radius: 3px;
        }
        QSlider::sub-page:horizontal {
            background: #2f6f65;
            border-radius: 3px;
        }
        QSlider::handle:horizontal {
            width: 14px;
            margin: -5px 0;
            background: #fffdf9;
            border: 2px solid #2f6f65;
            border-radius: 7px;
        }
        """


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
            self._details_card: QFrame | None = None
            self._decode_started = False
            self._preview_visible = False
            self._pending_autoplay = False

            self.setObjectName("PreviewRoot")
            self.setStyleSheet(_preview_stylesheet())

            self._metadata = QTextEdit()
            self._metadata.setReadOnly(True)
            self._metadata.setFixedHeight(160)
            self._metadata.setObjectName("DetailsText")
            metadata_policy = self._metadata.sizePolicy()
            metadata_policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
            metadata_policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
            self._metadata.setSizePolicy(metadata_policy)

            self._details_button = QPushButton(
                QCoreApplication.translate("FuzPreviewWidget", "\u25b6 Details")
            )
            self._details_button.setFlat(True)
            self._details_button.setObjectName("DetailsToggle")
            self._details_button.setCursor(Qt.CursorShape.PointingHandCursor)

            self._status = QLabel()
            self._status.setWordWrap(True)
            self._status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._status.setObjectName("StatusTitle")

            self._status_hint = QLabel()
            self._status_hint.setWordWrap(True)
            self._status_hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._status_hint.setObjectName("StatusHint")

            self._play_button = QPushButton(QCoreApplication.translate("FuzPreviewWidget", "Play"))
            self._stop_button = QPushButton(QCoreApplication.translate("FuzPreviewWidget", "Stop"))
            self._position_slider = QSlider(Qt.Orientation.Horizontal)
            self._time_label = QLabel("0:00 / 0:00")
            self._volume_slider = QSlider(Qt.Orientation.Horizontal)
            self._volume_value = QLabel()
            self._export_audio_button = QPushButton(QCoreApplication.translate("FuzPreviewWidget", "Export Audio"))
            self._export_lip_button = QPushButton(QCoreApplication.translate("FuzPreviewWidget", "Export LIP"))

            self._summary_widget = QWidget()
            self._summary_layout = QVBoxLayout()
            self._summary_layout.setContentsMargins(0, 0, 0, 0)
            self._summary_layout.setSpacing(6)
            self._summary_widget.setLayout(self._summary_layout)

            self._status_card: QFrame | None = None

            self._build_layout()
            self._wire_events()
            self._refresh_view()

        def showEvent(self, event) -> None:
            self._preview_visible = True
            super().showEvent(event)

            if not self._decode_started:
                self._start_decode()
                return

            if self._pending_autoplay and self._controller.state.can_play and not self._controller.state.is_playing:
                self._pending_autoplay = False
                self._controller.play()
                self._refresh_view()

        def hideEvent(self, event) -> None:
            self._preview_visible = False
            self._pending_autoplay = False
            if self._controller.state.is_playing:
                self._controller.stop()
                self._refresh_view()
            super().hideEvent(event)

        def closeEvent(self, event) -> None:
            self._preview_visible = False
            self._pending_autoplay = False
            self._cleanup_worker()
            self._controller.close()
            super().closeEvent(event)

        def _build_layout(self) -> None:
            self._volume_slider.setRange(0, 100)
            self._volume_slider.setValue(self._controller.state.volume)
            self._play_button.setObjectName("PrimaryButton")
            self._stop_button.setObjectName("DangerButton")
            self._export_audio_button.setObjectName("ExportButton")
            self._export_lip_button.setObjectName("ExportButton")
            self._time_label.setObjectName("TimeBadge")
            self._volume_value.setObjectName("VolumeValue")

            self._play_button.setMinimumHeight(38)
            self._stop_button.setMinimumHeight(38)
            self._export_audio_button.setMinimumHeight(34)
            self._export_lip_button.setMinimumHeight(34)
            self._time_label.setMinimumWidth(110)
            self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._volume_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            status_card = QFrame()
            status_card.setObjectName("StatusCard")
            status_layout = QVBoxLayout()
            status_layout.setContentsMargins(16, 14, 16, 14)
            status_layout.setSpacing(4)
            status_layout.addWidget(self._status)
            status_layout.addWidget(self._status_hint)
            status_card.setLayout(status_layout)
            self._status_card = status_card

            controls = QGroupBox(QCoreApplication.translate("FuzPreviewWidget", "Playback"))
            controls.setObjectName("PlaybackGroup")
            controls_layout = QGridLayout()
            controls_layout.setHorizontalSpacing(10)
            controls_layout.setVerticalSpacing(10)
            controls_layout.setContentsMargins(14, 18, 14, 14)
            controls_layout.setColumnStretch(0, 1)
            controls_layout.setColumnStretch(1, 1)
            controls_layout.addWidget(self._play_button, 0, 0)
            controls_layout.addWidget(self._stop_button, 0, 1)
            controls_layout.addWidget(self._time_label, 0, 2, 1, 2)
            controls_layout.addWidget(self._position_slider, 1, 0, 1, 4)
            controls_layout.addWidget(QLabel(QCoreApplication.translate("FuzPreviewWidget", "Volume")), 2, 0)
            controls_layout.addWidget(self._volume_slider, 2, 1, 1, 2)
            controls_layout.addWidget(self._volume_value, 2, 3)
            controls.setLayout(controls_layout)

            exports = QHBoxLayout()
            exports.setSpacing(8)
            exports.addWidget(self._export_audio_button)
            exports.addWidget(self._export_lip_button)

            info_card = QFrame()
            info_card.setObjectName("InfoCard")
            info_card.setMinimumWidth(260)
            info_layout = QVBoxLayout()
            info_layout.setContentsMargins(14, 14, 14, 14)
            info_layout.setSpacing(10)
            info_layout.addWidget(self._summary_widget)
            info_layout.addWidget(self._details_button)
            info_layout.addStretch(1)
            info_card.setLayout(info_layout)

            details_card = QFrame()
            details_card.setObjectName("InfoCard")
            details_card.setVisible(False)
            details_layout = QVBoxLayout()
            details_layout.setContentsMargins(14, 14, 14, 14)
            details_layout.setSpacing(0)
            details_layout.addWidget(self._metadata)
            details_card.setLayout(details_layout)
            self._details_card = details_card

            main_column = QVBoxLayout()
            main_column.setSpacing(10)
            main_column.addWidget(status_card)
            main_column.addWidget(controls)
            main_column.addLayout(exports)

            content = QHBoxLayout()
            content.setSpacing(12)
            content.addLayout(main_column, 7)
            content.addWidget(info_card, 5)

            root = QVBoxLayout()
            root.setContentsMargins(12, 12, 12, 12)
            root.setSpacing(12)
            root.addLayout(content)
            root.addWidget(details_card)
            root.addStretch()
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
            self._details_button.clicked.connect(self._toggle_details)

        def _toggle_details(self) -> None:
            visible = self._details_card is None or not self._details_card.isVisible()
            if self._details_card is not None:
                self._details_card.setVisible(visible)
            self._details_button.setText(
                QCoreApplication.translate("FuzPreviewWidget", "\u25bc Details")
                if visible
                else QCoreApplication.translate("FuzPreviewWidget", "\u25b6 Details")
            )

        def _start_decode(self) -> None:
            if self._decode_started:
                return
            self._decode_started = True

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
            should_autoplay = bool(
                self._settings.autoplay and self._preview_visible and self.isVisible() and not self.isHidden()
            )
            self._pending_autoplay = bool(result.success and result.wav_data and self._settings.autoplay and not should_autoplay)
            self._controller.apply_decode_result(result, autoplay=should_autoplay)
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

            detail_lines = self._unique_lines(state.metadata_lines + diagnostics)
            self._metadata.setPlainText("\n".join(detail_lines))
            self._set_summary_lines(state.metadata_lines[1:7] or state.metadata_lines)
            self._status.setText(state.status_text)
            self._status_hint.setText(self._build_status_hint(state.metadata_lines))
            self._play_button.setEnabled(state.can_play)
            self._play_button.setText(
                QCoreApplication.translate("FuzPreviewWidget", "Pause")
                if state.is_playing
                else QCoreApplication.translate("FuzPreviewWidget", "Play")
            )
            self._stop_button.setEnabled(state.can_play)
            self._position_slider.setEnabled(state.can_play and getattr(self._player, "supports_seek", True))
            self._volume_slider.setEnabled(state.can_play and getattr(self._player, "supports_volume", True))
            self._volume_value.setText(f"{state.volume}%")
            self._export_audio_button.setEnabled(state.can_export_audio)
            self._export_lip_button.setEnabled(state.can_export_lip)
            self._time_label.setText(self._controller.current_time_label())
            self._update_status_theme()

        def _set_summary_lines(self, lines: list[str]) -> None:
            while self._summary_layout.count():
                item = self._summary_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

            for line in lines:
                label = QLabel(line)
                label.setObjectName("SummaryItem")
                label.setWordWrap(True)
                label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self._summary_layout.addWidget(label)

        def _build_status_hint(self, metadata_lines: list[str]) -> str:
            preferred_indexes = (1, 2, 5)
            parts = [metadata_lines[index] for index in preferred_indexes if index < len(metadata_lines)]
            return "  |  ".join(parts)

        def _unique_lines(self, lines: list[str]) -> list[str]:
            seen: set[str] = set()
            ordered: list[str] = []
            for line in lines:
                if line in seen:
                    continue
                seen.add(line)
                ordered.append(line)
            return ordered

        def _update_status_theme(self) -> None:
            if self._status_card is None:
                return

            state = self._controller.state
            if state.has_error:
                background = "#fbe9e4"
                border = "#dfb19f"
                title = "#793523"
                hint = "#9a5a46"
            elif state.is_loading:
                background = "#fff4dd"
                border = "#e2c277"
                title = "#684f22"
                hint = "#8c7546"
            elif state.is_playing:
                background = "#e5f3ef"
                border = "#8cb9ae"
                title = "#184840"
                hint = "#3f6d64"
            else:
                background = "#f4eee6"
                border = "#d5c4ad"
                title = "#3c3228"
                hint = "#6b5e50"

            self._status_card.setStyleSheet(
                "QFrame#StatusCard {{"
                f"background-color: {background};"
                f"border: 1px solid {border};"
                "border-radius: 14px;"
                "}}"
                "QLabel#StatusTitle {{"
                f"color: {title};"
                "font-size: 15px;"
                "font-weight: 600;"
                "}}"
                "QLabel#StatusHint {{"
                f"color: {hint};"
                "font-size: 12px;"
                "}}"
            )

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
            self.setObjectName("PreviewRoot")
            self.setStyleSheet(_preview_stylesheet())
            layout = QVBoxLayout()
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(12)

            card = QFrame()
            card.setObjectName("InfoCard")
            card_layout = QVBoxLayout()
            card_layout.setContentsMargins(16, 16, 16, 16)
            card_layout.setSpacing(10)

            heading = QLabel(title)
            heading.setWordWrap(True)
            heading.setObjectName("StatusTitle")
            details = QTextEdit()
            details.setReadOnly(True)
            details.setPlainText("\n".join(lines))
            details.setObjectName("DetailsText")

            card_layout.addWidget(heading)
            card_layout.addWidget(details)
            card.setLayout(card_layout)

            layout.addWidget(card)
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

    error_lines = [
        QCoreApplication.translate("build_preview_widget", "File: {file_name}").format(file_name=file_name),
        QCoreApplication.translate("build_preview_widget", "Source: {source_label}").format(source_label=source_label),
    ]
    error_lines.extend(diagnostics)
    preview_diagnostics = list(diagnostics)
    if not MULTIMEDIA_AVAILABLE:
        if MCI_AVAILABLE:
            backend_line = QCoreApplication.translate("build_preview_widget", "Playback backend: MCI fallback")
            error_lines.append(backend_line)
            preview_diagnostics.append(backend_line)
            if settings.debug_logging:
                qt_line = QCoreApplication.translate("build_preview_widget", "PyQt6.QtMultimedia: {error}").format(
                    error=MULTIMEDIA_IMPORT_ERROR
                )
                error_lines.append(qt_line)
                preview_diagnostics.append(qt_line)
        else:
            qt_line = QCoreApplication.translate("build_preview_widget", "PyQt6.QtMultimedia: {error}").format(
                error=MULTIMEDIA_IMPORT_ERROR
            )
            backend_line = QCoreApplication.translate("build_preview_widget", "Playback backend: unavailable")
            error_lines.extend((qt_line, backend_line))
            preview_diagnostics.extend((qt_line, backend_line))

    if parse_error is not None:
        error_lines.append(QCoreApplication.translate("build_preview_widget", "Parse status: {error}").format(error=parse_error))
        return ErrorPreviewWidget(
            title=QCoreApplication.translate("build_preview_widget", "Invalid FUZ container."),
            lines=error_lines,
        )

    assert payload is not None
    return FuzPreviewWidget(
        payload=payload,
        decoder=decoder,
        settings=settings,
        set_setting=set_setting,
        diagnostics=tuple(preview_diagnostics),
    )
