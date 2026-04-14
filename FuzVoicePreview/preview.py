from __future__ import annotations

import pathlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .cache import LruCache
from .controller import PreviewController
from .decoder import AudioDecoder
from .models import DecodeResult, FuzPayload, PreviewSettings, PreviewSource, PreviewState
from .parser import FuzFormatError, parse_fuz_bytes
from .perf import PerformanceTrace
from .playback import MCI_AVAILABLE, PLAYBACK_COORDINATOR, MciPlaybackSnapshot, MciWavePlayerCore
from .translation import QCoreApplication


@dataclass(frozen=True)
class PreviewLoadRequest:
    file_name: str
    source: PreviewSource
    source_label: str
    file_path: str | None = None
    raw_data: bytes | bytearray | memoryview | None = None
    cache_key: str | None = None


@dataclass
class PreparedPreviewData:
    payload: FuzPayload | None
    parse_error: str | None
    diagnostics: tuple[str, ...]
    performance: PerformanceTrace


@dataclass
class DecodedPreviewData:
    result: DecodeResult
    performance: PerformanceTrace


# Show the compact metadata cards without overflowing the right-hand summary column.
MAX_SUMMARY_LINES = 7


def prepare_preview_data(
    request: PreviewLoadRequest,
    *,
    cache: LruCache[str, PreparedPreviewData] | None = None,
) -> PreparedPreviewData:
    performance = PerformanceTrace()
    cache_lookup_started = time.perf_counter()
    cached = cache.get(request.cache_key) if cache is not None and request.cache_key else None
    performance.record_seconds("preview_cache_lookup_ms", time.perf_counter() - cache_lookup_started)
    if cached is not None:
        performance.record_count("preview_cache_hit")
        return PreparedPreviewData(
            payload=cached.payload,
            parse_error=cached.parse_error,
            diagnostics=cached.diagnostics,
            performance=performance,
        )

    diagnostics: list[str] = []
    read_started = time.perf_counter()
    try:
        raw_data = _load_preview_bytes(request)
    except (OSError, ValueError) as exc:
        performance.record_seconds("preview_read_ms", time.perf_counter() - read_started)
        performance.record_seconds("preview_parse_ms", 0.0)
        diagnostics.append(f"{type(exc).__name__}: {exc}")
        performance.record_milliseconds(
            "preview_prepare_total_ms",
            sum(
                performance.measurements.get(name, 0.0)
                for name in (
                    "preview_cache_lookup_ms",
                    "preview_read_ms",
                    "preview_parse_ms",
                )
            ),
        )
        return PreparedPreviewData(
            payload=None,
            parse_error=QCoreApplication.translate("FuzPreviewWidget", "Unable to load preview data."),
            diagnostics=tuple(diagnostics),
            performance=performance,
        )
    performance.record_seconds("preview_read_ms", time.perf_counter() - read_started)

    parse_started = time.perf_counter()
    payload = None
    parse_error = None
    try:
        payload = parse_fuz_bytes(raw_data, file_name=request.file_name, source=request.source)
    except FuzFormatError as exc:
        parse_error = str(exc)
        diagnostics.append(_header_diagnostic(raw_data))
    else:
        if payload.audio_signature.label == "Unknown" or payload.container_label != "FUZ":
            diagnostics.append(_header_diagnostic(raw_data))
            diagnostics.append(_embedded_audio_header_diagnostic(payload))
    performance.record_seconds("preview_parse_ms", time.perf_counter() - parse_started)
    performance.record_milliseconds(
        "preview_prepare_total_ms",
        sum(
            performance.measurements.get(name, 0.0)
            for name in (
                "preview_cache_lookup_ms",
                "preview_read_ms",
                "preview_parse_ms",
            )
        ),
    )

    prepared = PreparedPreviewData(
        payload=payload,
        parse_error=parse_error,
        diagnostics=tuple(diagnostics),
        performance=performance,
    )
    if cache is not None and request.cache_key:
        cache.put(
            request.cache_key,
            PreparedPreviewData(
                payload=payload,
                parse_error=parse_error,
                diagnostics=tuple(diagnostics),
                performance=PerformanceTrace(),
            ),
        )
    return prepared


def _load_preview_bytes(request: PreviewLoadRequest) -> bytes:
    if request.file_path:
        return Path(request.file_path).read_bytes()
    if request.raw_data is None:
        raise ValueError("No preview payload source was provided.")
    if isinstance(request.raw_data, bytes):
        return request.raw_data
    if isinstance(request.raw_data, bytearray):
        return bytes(request.raw_data)
    if isinstance(request.raw_data, memoryview):
        return request.raw_data.tobytes()
    return bytes(request.raw_data)


def _header_diagnostic(raw_data: bytes) -> str:
    head = raw_data[:16]
    hex_head = " ".join(f"{byte:02X}" for byte in head) if head else "<empty>"
    ascii_head = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in head)
    return QCoreApplication.translate("FuzPreviewDiagnostics", "Header bytes: {hex_head} | {ascii_head}").format(
        hex_head=hex_head,
        ascii_head=ascii_head,
    )


def _embedded_audio_header_diagnostic(payload: FuzPayload) -> str:
    head = payload.audio_data[:16]
    hex_head = " ".join(f"{byte:02X}" for byte in head) if head else "<empty>"
    ascii_head = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in head)
    return QCoreApplication.translate(
        "FuzPreviewDiagnostics", "Embedded audio header: {hex_head} | {ascii_head}"
    ).format(
        hex_head=hex_head,
        ascii_head=ascii_head,
    )

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
        QStyle,
        QStyleOptionSlider,
        QStackedWidget,
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


def preferred_variant_mod_name(available_mod_names: list[str], ancestor_titles: list[str]) -> str | None:
    normalized_names: dict[str, str] = {}
    for mod_name in available_mod_names:
        stripped_name = mod_name.strip()
        if stripped_name and stripped_name.lower() not in normalized_names:
            normalized_names[stripped_name.lower()] = stripped_name

    for title in ancestor_titles:
        stripped_title = title.strip()
        if not stripped_title:
            continue
        match = normalized_names.get(stripped_title.lower())
        if match is not None:
            return match
    return None


if BASIC_QT_AVAILABLE:  # pragma: no cover - exercised only inside MO2 / PyQt6 runtime
    class ClickableSlider(QSlider):
        def mousePressEvent(self, event) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                option = QStyleOptionSlider()
                self.initStyleOption(option)
                handle_rect = self.style().subControlRect(
                    QStyle.ComplexControl.CC_Slider,
                    option,
                    QStyle.SubControl.SC_SliderHandle,
                    self,
                )
                if handle_rect.contains(event.position().toPoint()):
                    super().mousePressEvent(event)
                    return

                if self.orientation() == Qt.Orientation.Horizontal:
                    position = round(event.position().x())
                    span = max(1, self.width())
                    upside_down = self.invertedAppearance()
                    if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
                        upside_down = not upside_down
                else:
                    position = round(event.position().y())
                    span = max(1, self.height())
                    upside_down = not self.invertedAppearance()

                value = QStyle.sliderValueFromPosition(
                    self.minimum(),
                    self.maximum(),
                    position,
                    span,
                    upside_down,
                )
                self.setValue(value)
                event.accept()
                return

            super().mousePressEvent(event)


    class PreviewPreparationWorker(QObject):
        finished = pyqtSignal(object)

        def __init__(self, request: PreviewLoadRequest, cache: LruCache[str, PreparedPreviewData] | None):
            super().__init__()
            self._request = request
            self._cache = cache

        def run(self) -> None:
            self.finished.emit(prepare_preview_data(self._request, cache=self._cache))


    class DecodeWorker(QObject):
        finished = pyqtSignal(object)

        def __init__(self, payload: FuzPayload, decoder: AudioDecoder):
            super().__init__()
            self._payload = payload
            self._decoder = decoder

        def run(self) -> None:
            performance = PerformanceTrace()
            result = self._decoder.decode_payload(self._payload, trace=performance)
            self.finished.emit(DecodedPreviewData(result=result, performance=performance))


    class NullMediaPlayerAdapter(QObject):
        supports_seek = False
        supports_volume = False
        position_changed = pyqtSignal(int)
        duration_changed = pyqtSignal(int)
        playback_changed = pyqtSignal(bool)
        error_changed = pyqtSignal(str)

        def __init__(self, parent: QWidget | None = None, metric_callback: Callable[[str, float], None] | None = None):
            super().__init__(parent)
            self._metric_callback = metric_callback

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

            def __init__(self, parent: QWidget | None = None, metric_callback: Callable[[str, float], None] | None = None):
                super().__init__(parent)
                self._metric_callback = metric_callback
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
                if self._player.duration() > 0 and self._player.position() >= self._player.duration():
                    self._player.setPosition(0)
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
                    if self._player.duration() > 0 and self._player.position() >= self._player.duration():
                        self.position_changed.emit(self._player.position())
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
            supports_live_volume = True
            position_changed = pyqtSignal(int)
            duration_changed = pyqtSignal(int)
            playback_changed = pyqtSignal(bool)
            error_changed = pyqtSignal(str)

            def __init__(self, parent: QWidget | None = None, metric_callback: Callable[[str, float], None] | None = None):
                super().__init__(parent)
                self._metric_callback = metric_callback
                self._player = MciWavePlayerCore(metric_callback=self._emit_metric)
                self._snapshot = MciPlaybackSnapshot(position_ms=0, duration_ms=0, is_playing=False)
                self._timer = QTimer(self)
                self._timer.setInterval(120)
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

            def _emit_metric(self, name: str, value_ms: float) -> None:
                if self._metric_callback is not None:
                    self._metric_callback(name, value_ms)

        PlayerAdapterClass = MciWavePlayerAdapter
    else:
        PlayerAdapterClass = NullMediaPlayerAdapter
    PLAYBACK_AVAILABLE = MULTIMEDIA_AVAILABLE or MCI_AVAILABLE


    def _preview_stylesheet() -> str:
        return """
        QWidget#PreviewRoot {
            background-color: #f2f1ee;
            color: #2f2d2a;
            font-family: "Segoe UI";
        }
        QFrame#StatusCard,
        QFrame#InfoCard,
        QGroupBox#PlaybackGroup {
            background-color: #fbfaf8;
            border: 1px solid #d4cec5;
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
            color: #69635c;
            font-weight: 600;
        }
        QLabel#StatusTitle {
            font-size: 15px;
            font-weight: 600;
        }
        QLabel#StatusHint {
            color: #726b63;
            font-size: 12px;
        }
        QLabel#SummaryItem {
            background-color: #f6f4f0;
            border: 1px solid #e2ddd5;
            border-radius: 10px;
            padding: 8px 10px;
            color: #403c37;
        }
        QPushButton {
            background-color: #f4f2ee;
            color: #3b3834;
            border: 1px solid #c9c2b8;
            border-radius: 10px;
            padding: 8px 14px;
        }
        QPushButton:hover {
            background-color: #eeebe6;
        }
        QPushButton:pressed {
            background-color: #e5e1db;
        }
        QPushButton:disabled {
            background-color: #ebe8e3;
            color: #a19a92;
            border-color: #dad4cc;
        }
        QPushButton#PrimaryButton {
            background-color: #65717a;
            color: #ffffff;
            border-color: #5a666f;
            font-weight: 600;
        }
        QPushButton#PrimaryButton:hover {
            background-color: #707c85;
        }
        QPushButton#PrimaryButton:pressed {
            background-color: #55616a;
        }
        QPushButton#DangerButton {
            background-color: #efebe5;
            color: #4a4641;
            border-color: #cfc7bd;
            font-weight: 600;
        }
        QPushButton#DangerButton:hover {
            background-color: #e8e3dc;
        }
        QPushButton#ExportButton {
            font-weight: 600;
        }
        QPushButton#DetailsToggle {
            background-color: transparent;
            border: none;
            color: #5d5953;
            padding: 2px 0;
            text-align: left;
            font-weight: 600;
        }
        QPushButton#DetailsToggle:hover {
            color: #4d5a63;
        }
        QLabel#TimeBadge {
            background-color: #f1efeb;
            border: 1px solid #d1cbc2;
            border-radius: 10px;
            padding: 6px 10px;
            color: #56514b;
            font-weight: 600;
        }
        QLabel#VolumeValue {
            color: #666059;
            font-weight: 600;
            min-width: 40px;
        }
        QTextEdit#DetailsText {
            background-color: #faf9f6;
            border: 1px solid #e2ddd5;
            border-radius: 10px;
            padding: 4px;
            selection-background-color: #ccd3d8;
        }
        QSlider::groove:horizontal {
            height: 4px;
            background: #d1cbc3;
            border-radius: 2px;
        }
        QSlider::sub-page:horizontal {
            background: #7b868d;
            border-radius: 2px;
        }
        QSlider::add-page:horizontal {
            background: #d1cbc3;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            width: 12px;
            margin: -6px 0;
            background: #fcfbf9;
            border: 2px solid #7b868d;
            border-radius: 6px;
        }
        """


    class FuzPreviewWidget(QWidget):
        def __init__(
            self,
            *,
            request: PreviewLoadRequest,
            decoder: AudioDecoder,
            settings: PreviewSettings,
            set_setting: Callable[[str, object], None],
            diagnostics: tuple[str, ...],
            preview_cache: LruCache[str, PreparedPreviewData] | None,
        ):
            super().__init__()
            self._request = request
            self._payload: FuzPayload | None = None
            self._settings = settings
            self._set_setting = set_setting
            self._diagnostics = diagnostics
            self._preview_cache = preview_cache
            self._performance = PerformanceTrace()
            self._player = PlayerAdapterClass(self, self._record_player_metric)
            self._controller: PreviewController | None = None
            self._decoder = decoder
            self._prepare_thread: QThread | None = None
            self._prepare_worker: PreviewPreparationWorker | None = None
            self._decode_thread: QThread | None = None
            self._decode_worker: DecodeWorker | None = None
            self._details_card: QFrame | None = None
            self._prepare_started = False
            self._decode_started = False
            self._preview_visible = False
            self._pending_autoplay = False
            self._autoplay_requested_at: float | None = None
            self._last_detail_text = ""
            self._last_summary_lines: tuple[str, ...] = ()
            self._last_status_theme: tuple[bool, bool, bool] | None = None
            self._last_status_text = ""
            self._last_status_hint = ""
            self._placeholder_state = PreviewState(
                status_text=QCoreApplication.translate("FuzPreviewWidget", "Preparing preview..."),
                is_loading=True,
                metadata_lines=self._initial_metadata_lines(),
                volume=self._settings.default_volume,
            )

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
            self._position_slider = ClickableSlider(Qt.Orientation.Horizontal)
            self._time_label = QLabel("0:00 / 0:00")
            self._volume_slider = ClickableSlider(Qt.Orientation.Horizontal)
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
            super().showEvent(event)

            if self._sync_preferred_variant():
                return

            self._preview_visible = True

            if not self._prepare_started:
                self._start_prepare()
                return

            if self._controller is not None and not self._decode_started:
                self._start_decode()
                return

            state = self._active_state()
            if self._pending_autoplay and state.can_play and not state.is_playing and self._controller is not None:
                self._pending_autoplay = False
                self._autoplay_requested_at = time.perf_counter()
                self._controller.play()
                self._refresh_view()

        def hideEvent(self, event) -> None:
            self._preview_visible = False
            self._pending_autoplay = False
            if self._controller is not None and self._controller.state.is_playing:
                self._controller.stop()
                self._refresh_view()
            super().hideEvent(event)

        def closeEvent(self, event) -> None:
            self._preview_visible = False
            self._pending_autoplay = False
            self._cleanup_prepare_worker()
            self._cleanup_worker()
            if self._controller is not None:
                self._controller.close()
            super().closeEvent(event)

        def _initial_metadata_lines(self) -> list[str]:
            return [
                QCoreApplication.translate("FuzPreviewWidget", "File: {file_name}").format(file_name=self._request.file_name),
                QCoreApplication.translate("FuzPreviewWidget", "Source: {source_label}").format(
                    source_label=self._request.source_label
                ),
            ]

        def _active_state(self) -> PreviewState:
            return self._controller.state if self._controller is not None else self._placeholder_state

        def _sync_preferred_variant(self) -> bool:
            stack = self.parentWidget()
            if not isinstance(stack, QStackedWidget):
                return False
            if bool(stack.property("_fuz_preferred_variant_synced")):
                return False

            available_mod_names = [str(stack.widget(index).property("modName") or "") for index in range(stack.count())]
            preferred_mod_name = preferred_variant_mod_name(available_mod_names, self._ancestor_window_titles(stack.window()))
            stack.setProperty("_fuz_preferred_variant_synced", True)
            if preferred_mod_name is None:
                return False

            current_widget = stack.currentWidget()
            for index in range(stack.count()):
                candidate = stack.widget(index)
                candidate_name = str(candidate.property("modName") or "").strip()
                if candidate_name.lower() != preferred_mod_name.lower():
                    continue
                if candidate is current_widget:
                    return False
                stack.setCurrentWidget(candidate)
                return True

            return False

        def _ancestor_window_titles(self, widget: QWidget | None) -> list[str]:
            titles: list[str] = []
            current = widget.parentWidget() if widget is not None else None
            while current is not None:
                title = current.windowTitle().strip()
                if title:
                    titles.append(title)
                current = current.parentWidget()
            return titles

        def _build_layout(self) -> None:
            self._volume_slider.setRange(0, 100)
            self._volume_slider.setValue(self._active_state().volume)
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
            self._position_slider.valueChanged.connect(self._seek)
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

        def _start_prepare(self) -> None:
            if self._prepare_started:
                return
            self._prepare_started = True
            self._placeholder_state.is_loading = True
            self._placeholder_state.has_error = False
            self._placeholder_state.error_text = None
            self._placeholder_state.status_text = QCoreApplication.translate("FuzPreviewWidget", "Preparing preview...")
            self._refresh_view()

            self._prepare_thread = QThread()
            self._prepare_worker = PreviewPreparationWorker(self._request, self._preview_cache)
            self._prepare_worker.moveToThread(self._prepare_thread)
            self._prepare_thread.started.connect(self._prepare_worker.run)
            self._prepare_worker.finished.connect(self._on_preparation_finished)
            self._prepare_worker.finished.connect(self._prepare_thread.quit)
            self._prepare_worker.finished.connect(self._prepare_worker.deleteLater)
            self._prepare_thread.finished.connect(self._finalize_prepare_worker_cleanup)
            self._prepare_thread.finished.connect(self._prepare_thread.deleteLater)
            self._prepare_thread.start()

        def _cleanup_prepare_worker(self) -> None:
            if self._prepare_thread is None:
                assert self._prepare_worker is None
                return
            if self._prepare_thread.isRunning():
                self._prepare_thread.quit()
                return
            self._finalize_prepare_worker_cleanup()

        def _finalize_prepare_worker_cleanup(self) -> None:
            if self._prepare_thread is None or self._prepare_thread.isRunning():
                return
            self._prepare_worker = None
            self._prepare_thread = None

        def _on_preparation_finished(self, prepared: PreparedPreviewData) -> None:
            self._performance.extend(prepared.performance)
            self._diagnostics = tuple(self._unique_lines(list(self._diagnostics) + list(prepared.diagnostics)))
            self._cleanup_prepare_worker()

            if prepared.parse_error is not None or prepared.payload is None:
                self._payload = None
                self._placeholder_state.is_loading = False
                self._placeholder_state.has_error = True
                self._placeholder_state.error_text = prepared.parse_error
                self._placeholder_state.status_text = prepared.parse_error or QCoreApplication.translate(
                    "FuzPreviewWidget", "Invalid FUZ container."
                )
                self._refresh_view()
                return

            self._payload = prepared.payload
            self._placeholder_state.is_loading = False
            self._controller = PreviewController(
                payload=prepared.payload,
                player=self._player,
                settings=self._settings,
                on_setting_changed=self._set_setting,
            )
            volume_slider = getattr(self, "_volume_slider", None)
            if volume_slider is not None:
                with QSignalBlocker(volume_slider):
                    volume_slider.setValue(self._controller.state.volume)
            self._refresh_view()
            if self._preview_visible and not self._decode_started:
                self._start_decode()

        def _start_decode(self) -> None:
            if self._decode_started:
                return
            self._decode_started = True
            if self._controller is None:
                self._decode_started = False
                return

            if not PLAYBACK_AVAILABLE:
                self._on_decode_finished(
                    DecodedPreviewData(
                        result=DecodeResult.failed(
                            QCoreApplication.translate("FuzPreviewWidget", "No playback backend is available.")
                        ),
                        performance=PerformanceTrace(),
                    )
                )
                return

            self._controller.mark_loading()
            self._refresh_view()

            self._decode_thread = QThread()
            self._decode_worker = DecodeWorker(self._payload, self._decoder)
            self._decode_worker.moveToThread(self._decode_thread)
            self._decode_thread.started.connect(self._decode_worker.run)
            self._decode_worker.finished.connect(self._on_decode_finished)
            self._decode_worker.finished.connect(self._decode_thread.quit)
            self._decode_worker.finished.connect(self._decode_worker.deleteLater)
            self._decode_thread.finished.connect(self._finalize_decode_worker_cleanup)
            self._decode_thread.finished.connect(self._decode_thread.deleteLater)
            self._decode_thread.start()

        def _cleanup_worker(self) -> None:
            if self._decode_thread is None:
                assert self._decode_worker is None
                return
            if self._decode_thread.isRunning():
                self._decode_thread.quit()
                return
            self._finalize_decode_worker_cleanup()

        def _finalize_decode_worker_cleanup(self) -> None:
            if self._decode_thread is None or self._decode_thread.isRunning():
                return
            self._decode_worker = None
            self._decode_thread = None

        def _on_decode_finished(self, decoded: DecodedPreviewData) -> None:
            result = decoded.result
            self._performance.extend(decoded.performance)
            should_autoplay = bool(
                self._settings.autoplay and self._preview_visible and self.isVisible() and not self.isHidden()
            )
            self._pending_autoplay = bool(result.success and result.wav_data and self._settings.autoplay and not should_autoplay)
            if should_autoplay:
                self._autoplay_requested_at = time.perf_counter()
            if self._controller is not None:
                self._controller.apply_decode_result(result, autoplay=should_autoplay, trace=self._performance)
            self._refresh_view()
            self._cleanup_worker()

        def _on_position_changed(self, value: int) -> None:
            if self._controller is None:
                return
            self._controller.update_position(value)
            with QSignalBlocker(self._position_slider):
                self._position_slider.setValue(value)
            self._time_label.setText(self._controller.current_time_label())

        def _on_duration_changed(self, value: int) -> None:
            if self._controller is None:
                return
            self._controller.update_position(self._controller.state.position_ms, value)
            self._position_slider.setRange(0, max(0, value))
            self._time_label.setText(self._controller.current_time_label())

        def _on_playback_changed(self, is_playing: bool) -> None:
            if self._controller is None:
                return
            self._controller.state.is_playing = is_playing
            if is_playing:
                if self._autoplay_requested_at is not None:
                    self._performance.record_seconds("autoplay_to_playing_ms", time.perf_counter() - self._autoplay_requested_at)
                    self._autoplay_requested_at = None
                self._controller.state.status_text = QCoreApplication.translate("FuzPreviewWidget", "Playing.")
            elif (
                self._controller.state.duration_ms > 0
                and self._controller.state.position_ms >= self._controller.state.duration_ms
            ):
                self._autoplay_requested_at = None
                self._controller.state.status_text = QCoreApplication.translate("FuzPreviewWidget", "Ready to replay.")
            else:
                self._autoplay_requested_at = None
                self._controller.state.status_text = (
                    QCoreApplication.translate("FuzPreviewWidget", "Stopped.")
                    if self._controller.state.position_ms == 0
                    else QCoreApplication.translate("FuzPreviewWidget", "Paused.")
                )
            self._refresh_view()

        def _on_player_error(self, error_text: str) -> None:
            state = self._active_state()
            state.has_error = True
            state.error_text = error_text
            state.status_text = error_text
            self._refresh_view()

        def _toggle_playback(self) -> None:
            if self._controller is None:
                return
            self._controller.toggle_play_pause()
            self._refresh_view()

        def _stop_playback(self) -> None:
            if self._controller is None:
                return
            self._controller.stop()
            self._refresh_view()

        def _change_volume(self, value: int) -> None:
            if self._controller is None:
                return
            started = time.perf_counter()
            self._controller.set_volume(value)
            self._performance.record_seconds("volume_change_ms", time.perf_counter() - started)
            self._refresh_view()

        def _seek(self, value: int) -> None:
            if self._controller is None or not getattr(self._player, "supports_seek", True):
                return
            started = time.perf_counter()
            self._player.set_position(value)
            self._controller.update_position(value)
            self._performance.record_seconds("seek_response_ms", time.perf_counter() - started)
            self._time_label.setText(self._controller.current_time_label())

        def _record_player_metric(self, name: str, value_ms: float) -> None:
            self._performance.record_milliseconds(name, value_ms)

        def _refresh_view(self) -> None:
            state = self._active_state()
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
            if self._settings.debug_logging:
                diagnostics.extend(self._performance.lines())

            detail_lines = self._unique_lines(state.metadata_lines + diagnostics)
            detail_text = "\n".join(detail_lines)
            if detail_text != self._last_detail_text:
                self._metadata.setPlainText(detail_text)
                self._last_detail_text = detail_text

            summary_lines = tuple(state.metadata_lines[1:MAX_SUMMARY_LINES] or state.metadata_lines)
            if summary_lines != self._last_summary_lines:
                self._set_summary_lines(list(summary_lines))
                self._last_summary_lines = summary_lines

            if state.status_text != self._last_status_text:
                self._status.setText(state.status_text)
                self._last_status_text = state.status_text

            status_hint = self._build_status_hint(state.metadata_lines)
            if status_hint != self._last_status_hint:
                self._status_hint.setText(status_hint)
                self._last_status_hint = status_hint
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
            if self._controller is not None:
                self._time_label.setText(self._controller.current_time_label())
            else:
                self._time_label.setText("0:00 / 0:00")
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

            state = self._active_state()
            theme_key = (state.has_error, state.is_loading, state.is_playing)
            if theme_key == self._last_status_theme:
                return
            self._last_status_theme = theme_key
            if state.has_error:
                background = "#f4ece8"
                border = "#d6beb6"
                title = "#65463f"
                hint = "#826760"
            elif state.is_loading:
                background = "#f5f1e7"
                border = "#d8cdb0"
                title = "#665c45"
                hint = "#83785e"
            elif state.is_playing:
                background = "#eceff1"
                border = "#bcc4c8"
                title = "#334049"
                hint = "#58636a"
            else:
                background = "#f3f1ed"
                border = "#d0c9c0"
                title = "#3c3935"
                hint = "#69625a"

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
            if self._payload is None:
                return
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
            if self._payload is None:
                return
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
    request: PreviewLoadRequest,
    decoder: AudioDecoder,
    settings: PreviewSettings,
    set_setting: Callable[[str, object], None],
    diagnostics: tuple[str, ...],
    preview_cache: LruCache[str, PreparedPreviewData] | None = None,
):
    if not BASIC_QT_AVAILABLE:
        raise RuntimeError(
            QCoreApplication.translate("build_preview_widget", "PyQt6 runtime is unavailable: {error}").format(
                error=BASIC_QT_IMPORT_ERROR
            )
        )

    preview_diagnostics = list(diagnostics)
    if not MULTIMEDIA_AVAILABLE:
        if MCI_AVAILABLE:
            backend_line = QCoreApplication.translate("build_preview_widget", "Playback backend: MCI fallback")
            preview_diagnostics.append(backend_line)
            if settings.debug_logging:
                qt_line = QCoreApplication.translate("build_preview_widget", "PyQt6.QtMultimedia: {error}").format(
                    error=MULTIMEDIA_IMPORT_ERROR
                )
                preview_diagnostics.append(qt_line)
        else:
            qt_line = QCoreApplication.translate("build_preview_widget", "PyQt6.QtMultimedia: {error}").format(
                error=MULTIMEDIA_IMPORT_ERROR
            )
            backend_line = QCoreApplication.translate("build_preview_widget", "Playback backend: unavailable")
            preview_diagnostics.extend((qt_line, backend_line))
    return FuzPreviewWidget(
        request=request,
        decoder=decoder,
        settings=settings,
        set_setting=set_setting,
        diagnostics=tuple(preview_diagnostics),
        preview_cache=preview_cache,
    )
