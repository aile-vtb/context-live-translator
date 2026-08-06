from __future__ import annotations

import shutil
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from functools import partial

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .audio import (
    MAX_GAIN_DB,
    list_audio_sources,
    meter_value_to_threshold,
    threshold_to_meter_value,
)
from .config import AppConfig, normalize_audio_routes, save_config
from .controller import AppController
from .doctor import format_checks, run_doctor
from .model_manager import (
    WHISPER_MODELS,
    DownloadCancelled,
    discover_whisper_models,
    download_whisper_model,
    managed_whisper_path,
    validate_whisper_model,
)
from .models import (
    SOURCE_LANGUAGES,
    TARGET_LANGUAGES,
    AudioRouteConfig,
    AudioSource,
    SegmentStatus,
    TranscriptSegment,
)

STATUS_LABELS = {
    SegmentStatus.RECOGNIZED: "已辨識",
    SegmentStatus.TRANSLATING: "翻譯中",
    SegmentStatus.PROVISIONAL: "暫定",
    SegmentStatus.REVISING: "回修中",
    SegmentStatus.FINAL: "已鎖定",
    SegmentStatus.ERROR: "錯誤",
}

STATUS_COLORS = {
    SegmentStatus.RECOGNIZED: "#64748b",
    SegmentStatus.TRANSLATING: "#2563eb",
    SegmentStatus.PROVISIONAL: "#d97706",
    SegmentStatus.REVISING: "#7c3aed",
    SegmentStatus.FINAL: "#15803d",
    SegmentStatus.ERROR: "#dc2626",
}


class ModelDownloadThread(QThread):
    progress = Signal(int, str)
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, model_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model_key = model_key
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            path = download_whisper_model(
                self.model_key,
                self.progress.emit,
                self.cancel_event,
            )
        except DownloadCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.completed.emit(str(path))


class AudioRouteCard(QFrame):
    def __init__(
        self,
        route: AudioRouteConfig,
        on_device: Callable[[str, object], None],
        on_gain: Callable[[str, float], None],
        on_threshold: Callable[[str, float], None],
        on_remove: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.route_id = route.id
        self._on_device = on_device
        self.setFrameShape(QFrame.Shape.StyledPanel)
        grid = QGridLayout(self)
        self.enabled = QCheckBox(f"啟用 · ID: {route.id}")
        self.enabled.setChecked(route.enabled)
        self.label_edit = QLineEdit(route.label)
        self.label_edit.setPlaceholderText("例如：我的麥克風、Discord 朋友")
        self.language_combo = QComboBox()
        for code, spec in SOURCE_LANGUAGES.items():
            self.language_combo.addItem(spec.display_name, code)
        self.language_combo.setCurrentIndex(
            max(0, self.language_combo.findData(route.source_language))
        )
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(480)
        self.gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(0, int(MAX_GAIN_DB))
        self.gain_slider.setValue(round(route.gain_db))
        self.gain_value = QLabel(f"+{round(route.gain_db)} dB")
        self.level = QProgressBar()
        self.level.setRange(0, 1000)
        self.level.setTextVisible(False)
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setRange(0, 1000)
        self.threshold_slider.setValue(threshold_to_meter_value(route.threshold))
        self.threshold_value = QLabel()
        self.remove_button = QPushButton("移除")

        grid.addWidget(self.enabled, 0, 0)
        grid.addWidget(QLabel("名稱"), 0, 1)
        grid.addWidget(self.label_edit, 0, 2)
        grid.addWidget(QLabel("來源語言"), 0, 3)
        grid.addWidget(self.language_combo, 0, 4)
        grid.addWidget(self.remove_button, 0, 5)
        grid.addWidget(QLabel("監聽裝置"), 1, 0)
        grid.addWidget(self.device_combo, 1, 1, 1, 5)
        grid.addWidget(QLabel("輸入增益"), 2, 0)
        grid.addWidget(self.gain_slider, 2, 1, 1, 2)
        grid.addWidget(self.gain_value, 2, 3)
        grid.addWidget(QLabel("即時音量"), 3, 0)
        grid.addWidget(self.level, 3, 1, 1, 5)
        grid.addWidget(QLabel("語音門檻"), 4, 0)
        grid.addWidget(self.threshold_slider, 4, 1, 1, 2)
        grid.addWidget(self.threshold_value, 4, 3, 1, 3)

        self.device_combo.currentIndexChanged.connect(self._device_changed)
        self.gain_slider.valueChanged.connect(
            lambda value: self._gain_changed(value, on_gain)
        )
        self.threshold_slider.valueChanged.connect(
            lambda value: self._threshold_changed(value, on_threshold)
        )
        self.remove_button.clicked.connect(lambda: on_remove(self.route_id))
        self._threshold_changed(self.threshold_slider.value(), on_threshold)

    def populate_sources(self, sources: list[AudioSource], fingerprint: str) -> bool:
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem("請選擇音訊來源", None)
        for group_kind, group_name in (
            ("input", "── 麥克風／音訊介面／虛擬輸入 ──"),
            ("loopback", "── Windows 系統播放端點 ──"),
        ):
            group = [source for source in sources if source.kind == group_kind]
            if not group:
                continue
            self.device_combo.addItem(group_name, None)
            header = self.device_combo.model().item(self.device_combo.count() - 1)
            if header:
                header.setEnabled(False)
                header.setForeground(QColor("#64748b"))
            for source in group:
                self.device_combo.addItem(source.label, source)
        match = next(
            (
                index
                for index in range(self.device_combo.count())
                if isinstance(self.device_combo.itemData(index), AudioSource)
                and self.device_combo.itemData(index).fingerprint == fingerprint
            ),
            0,
        )
        self.device_combo.setCurrentIndex(match)
        self.device_combo.blockSignals(False)
        if match:
            self._device_changed(match)
        return bool(match)

    def route_config(self) -> AudioRouteConfig:
        source = self.device_combo.currentData()
        return AudioRouteConfig(
            id=self.route_id,
            label=self.label_edit.text().strip() or self.route_id,
            source_fingerprint=(source.fingerprint if isinstance(source, AudioSource) else ""),
            source_language=str(self.language_combo.currentData()),
            gain_db=float(self.gain_slider.value()),
            threshold=meter_value_to_threshold(self.threshold_slider.value()),
            enabled=self.enabled.isChecked(),
            context_group_id="conversation",
        )

    def set_locked(self, locked: bool) -> None:
        for widget in (
            self.enabled,
            self.label_edit,
            self.language_combo,
            self.device_combo,
            self.gain_slider,
            self.threshold_slider,
            self.remove_button,
        ):
            widget.setEnabled(not locked)

    def _device_changed(self, index: int) -> None:
        source = self.device_combo.itemData(index)
        self.level.setValue(0)
        self._on_device(self.route_id, source)

    def _gain_changed(self, value: int, callback: Callable[[str, float], None]) -> None:
        self.gain_value.setText(f"+{value} dB")
        callback(self.route_id, value)

    def _threshold_changed(
        self, value: int, callback: Callable[[str, float], None]
    ) -> None:
        threshold = meter_value_to_threshold(value)
        self.threshold_value.setText(f"{value / 10:.1f}% / RMS {threshold:.4f}")
        callback(self.route_id, threshold)


class SegmentCard(QFrame):
    def __init__(self, segment: TranscriptSegment) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        header = QHBoxLayout()
        self.time_label = QLabel()
        self.language_label = QLabel()
        self.status_label = QLabel()
        header.addWidget(self.time_label)
        header.addWidget(self.language_label)
        header.addStretch()
        header.addWidget(self.status_label)
        layout.addLayout(header)
        self.source_label = QLabel()
        self.source_label.setObjectName("sourceText")
        self.source_label.setWordWrap(True)
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.translation_label = QLabel()
        self.translation_label.setObjectName("translationText")
        self.translation_label.setWordWrap(True)
        self.translation_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.source_label)
        layout.addWidget(self.translation_label)
        self.update_segment(segment)

    def update_segment(self, segment: TranscriptSegment) -> None:
        stamp = datetime.fromtimestamp(segment.started_at).strftime("%H:%M:%S")
        self.time_label.setText(stamp)
        confidence = f"{segment.language_probability:.0%}"
        uncertain = " · 語言不確定" if segment.source_language_uncertain else ""
        self.language_label.setText(
            f"{segment.route_label} · {segment.source_language} · {confidence}{uncertain}"
        )
        status = STATUS_LABELS[segment.status]
        if segment.revision:
            status += f" · 修訂 {segment.revision}"
        self.status_label.setText(status)
        color = STATUS_COLORS[segment.status]
        self.status_label.setStyleSheet(f"font-weight: 700; color: {color};")
        source_prefix = "來源（已依上下文修訂）" if segment.revision else "來源"
        self.source_label.setText(f"{source_prefix}：{segment.source_text}")
        self.source_label.setToolTip(
            f"Whisper 原始辨識：{segment.raw_asr_text}"
            if segment.source_text != segment.raw_asr_text
            else ""
        )
        if segment.translation:
            self.translation_label.setText(
                f"{segment.target_language.display_name}：{segment.translation}"
            )
        else:
            self.translation_label.setText(
                segment.error
                or f"{segment.target_language.display_name}：翻譯中…"
            )
        self.translation_label.setStyleSheet(
            "font-size: 16px; font-weight: 600;"
            + (" color: #dc2626;" if segment.error else "")
        )
        self.setToolTip(segment.error or "")


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.config.audio_routes = normalize_audio_routes(config.audio_routes)
        self.controller = AppController(config)
        self.sources: list[AudioSource] = []
        self.route_cards: dict[str, AudioRouteCard] = {}
        self._download_thread: ModelDownloadThread | None = None
        self._close_after_download = False
        self.segment_items: dict[str, tuple[QListWidgetItem, SegmentCard]] = {}
        self._closing = False
        self.setWindowTitle(f"Context Live Translator v{__version__}")
        self.resize(1060, 820)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._build_main_tab()
        self._build_model_tab()
        self._build_overlay_tab()
        self._build_diagnostics_tab()
        self._connect_controller()
        QTimer.singleShot(0, self.refresh_sources)
        QTimer.singleShot(0, self._detect_whisper_models)
        QTimer.singleShot(0, self._initialize_overlay)

    def _build_main_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)

        language_box = QGroupBox("字幕輸出語言（所有音訊來源共用）")
        language_form = QGridLayout(language_box)
        self.target_combo = QComboBox()
        for code, spec in TARGET_LANGUAGES.items():
            self.target_combo.addItem(spec.display_name, code)
        self.target_combo.addItem("自訂語言…", "__custom__")
        target_index = self.target_combo.findData(self.config.target_language_code)
        is_builtin = (
            self.config.target_language_code in TARGET_LANGUAGES
            and TARGET_LANGUAGES[self.config.target_language_code].display_name
            == self.config.target_language_name
        )
        self.target_combo.setCurrentIndex(
            target_index if target_index >= 0 and is_builtin else self.target_combo.count() - 1
        )
        self.custom_target_code = QLineEdit(self.config.target_language_code)
        self.custom_target_code.setPlaceholderText("例如 pt-BR")
        self.custom_target_name = QLineEdit(self.config.target_language_name)
        self.custom_target_name.setPlaceholderText("例如 Português do Brasil")
        self.custom_target_instruction = QLineEdit(self.config.target_language_instruction)
        self.custom_target_instruction.setPlaceholderText("可選的翻譯風格／地區用語指示")
        language_form.addWidget(QLabel("單一目標語言"), 0, 0)
        language_form.addWidget(self.target_combo, 0, 1, 1, 3)
        language_form.addWidget(QLabel("自訂代碼"), 1, 0)
        language_form.addWidget(self.custom_target_code, 1, 1)
        language_form.addWidget(QLabel("自訂名稱"), 1, 2)
        language_form.addWidget(self.custom_target_name, 1, 3)
        language_form.addWidget(QLabel("自訂指示"), 2, 0)
        language_form.addWidget(self.custom_target_instruction, 2, 1, 1, 3)
        layout.addWidget(language_box)

        audio_box = QGroupBox("音訊來源（各路獨立擷取與 VAD，不會先混音）")
        audio_layout = QVBoxLayout(audio_box)
        self.routes_layout = QVBoxLayout()
        audio_layout.addLayout(self.routes_layout)
        route_buttons = QHBoxLayout()
        self.add_route_button = QPushButton("新增音訊來源")
        self.refresh_button = QPushButton("重新掃描")
        route_buttons.addWidget(self.add_route_button)
        route_buttons.addWidget(self.refresh_button)
        route_buttons.addStretch()
        audio_layout.addLayout(route_buttons)
        for route in self.config.audio_routes:
            self._create_route_card(route)
        layout.addWidget(audio_box)

        controls = QHBoxLayout()
        self.start_button = QPushButton("開始")
        self.pause_button = QPushButton("暫停")
        self.stop_button = QPushButton("停止")
        self.clear_button = QPushButton("清除畫面")
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        for button in (
            self.start_button,
            self.pause_button,
            self.stop_button,
            self.clear_button,
        ):
            button.setMinimumHeight(38)
            controls.addWidget(button)
        layout.addLayout(controls)

        self.timeline = QListWidget()
        self.timeline.setObjectName("timeline")
        self.timeline.setSpacing(6)
        self.timeline.setAlternatingRowColors(True)
        layout.addWidget(self.timeline, 1)
        self.status = QLabel("請選擇音訊來源與本機模型")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tabs.addTab(page, "即時翻譯")

        self.target_combo.currentIndexChanged.connect(self._target_changed)
        self.add_route_button.clicked.connect(self._add_route)
        self.refresh_button.clicked.connect(self.refresh_sources)
        self.start_button.clicked.connect(self._start_clicked)
        self.pause_button.clicked.connect(self.controller.pause)
        self.stop_button.clicked.connect(self.controller.stop)
        self.clear_button.clicked.connect(self.controller.clear)
        self._target_changed()

    def _build_model_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        model_box = QGroupBox("本機模型（只在使用者按下下載後連線）")
        form = QGridLayout(model_box)
        self.whisper_path = QLineEdit(self.config.whisper_model_path)
        self.whisper_browse = QPushButton("選擇目錄")
        self.whisper_detected = QComboBox()
        self.whisper_detect = QPushButton("偵測既有模型")
        self.whisper_use_detected = QPushButton("使用偵測結果")
        self.whisper_model_choice = QComboBox()
        for key, spec in WHISPER_MODELS.items():
            self.whisper_model_choice.addItem(spec.display_name, key)
        self.whisper_download = QPushButton("下載並安裝到使用者資料夾")
        self.whisper_cancel = QPushButton("取消下載")
        self.whisper_cancel.setEnabled(False)
        self.whisper_progress = QProgressBar()
        self.whisper_progress.setRange(0, 100)
        self.whisper_download_status = QLabel(
            "管理位置：%LOCALAPPDATA%\\ContextLiveTranslator\\models\\whisper"
        )
        self.whisper_download_status.setWordWrap(True)
        self.llama_path = QLineEdit(self.config.llama_server_path)
        self.llama_browse = QPushButton("選擇檔案")
        self.gguf_path = QLineEdit(self.config.llama_model_path)
        self.gguf_browse = QPushButton("選擇檔案")
        form.addWidget(QLabel("Whisper CTranslate2"), 0, 0)
        form.addWidget(self.whisper_path, 0, 1)
        form.addWidget(self.whisper_browse, 0, 2)
        form.addWidget(QLabel("偵測到的模型"), 1, 0)
        form.addWidget(self.whisper_detected, 1, 1)
        detected_buttons = QHBoxLayout()
        detected_buttons.addWidget(self.whisper_detect)
        detected_buttons.addWidget(self.whisper_use_detected)
        form.addLayout(detected_buttons, 1, 2)
        form.addWidget(QLabel("官方轉換模型"), 2, 0)
        form.addWidget(self.whisper_model_choice, 2, 1)
        download_buttons = QHBoxLayout()
        download_buttons.addWidget(self.whisper_download)
        download_buttons.addWidget(self.whisper_cancel)
        form.addLayout(download_buttons, 2, 2)
        form.addWidget(self.whisper_progress, 3, 1)
        form.addWidget(self.whisper_download_status, 3, 2)
        form.addWidget(QLabel("llama-server.exe"), 4, 0)
        form.addWidget(self.llama_path, 4, 1)
        form.addWidget(self.llama_browse, 4, 2)
        form.addWidget(QLabel("翻譯 GGUF（Gemma／Qwen／其他）"), 5, 0)
        form.addWidget(self.gguf_path, 5, 1)
        form.addWidget(self.gguf_browse, 5, 2)
        layout.addWidget(model_box)

        advanced = QGroupBox("效能與上下文")
        advanced_form = QFormLayout(advanced)
        self.compute_combo = QComboBox()
        for value, label in (
            ("auto", "Auto（優先 CUDA）"),
            ("cuda", "NVIDIA CUDA"),
            ("cpu", "CPU（不保證即時）"),
        ):
            self.compute_combo.addItem(label, value)
        self.compute_combo.setCurrentIndex(
            max(0, self.compute_combo.findData(self.config.whisper_device))
        )
        self.gpu_layers = QSpinBox()
        self.gpu_layers.setRange(0, 999)
        self.gpu_layers.setValue(self.config.llama_gpu_layers)
        self.context_size = QSpinBox()
        self.context_size.setRange(1024, 32768)
        self.context_size.setSingleStep(1024)
        self.context_size.setValue(self.config.llama_context)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(self.config.llama_port)
        self.revision_window = QSpinBox()
        self.revision_window.setRange(1, 8)
        self.revision_window.setValue(self.config.revision_window)
        self.finalization_seconds = QSpinBox()
        self.finalization_seconds.setRange(5, 120)
        self.finalization_seconds.setValue(self.config.finalization_seconds)
        advanced_form.addRow("Whisper 運算裝置", self.compute_combo)
        advanced_form.addRow("llama.cpp GPU layers", self.gpu_layers)
        advanced_form.addRow("llama.cpp context", self.context_size)
        advanced_form.addRow("llama.cpp localhost port", self.port)
        advanced_form.addRow("可回修句數", self.revision_window)
        advanced_form.addRow("無新內容後鎖定秒數", self.finalization_seconds)
        layout.addWidget(advanced)
        note = QLabel(
            "Gemma 會使用 JSON object 相容模式；Qwen 與其他 GGUF 優先使用 JSON Schema，"
            "遇到 llama.cpp 400 回應時自動回退。模型權重與使用條款由使用者自行取得及遵守。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.tabs.addTab(page, "模型與進階")

        self.whisper_browse.clicked.connect(self._browse_whisper)
        self.whisper_detect.clicked.connect(self._detect_whisper_models)
        self.whisper_use_detected.clicked.connect(self._use_detected_whisper)
        self.whisper_download.clicked.connect(self._start_whisper_download)
        self.whisper_cancel.clicked.connect(self._cancel_whisper_download)
        self.llama_browse.clicked.connect(
            partial(self._browse_file, self.llama_path, "Executable (*.exe);;All files (*)")
        )
        self.gguf_browse.clicked.connect(
            partial(self._browse_file, self.gguf_path, "GGUF model (*.gguf);;All files (*)")
        )

    def _build_diagnostics_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.doctor_output = QPlainTextEdit()
        self.doctor_output.setReadOnly(True)
        self.doctor_button = QPushButton("執行唯讀環境診斷")
        layout.addWidget(
            QLabel(
                "檢查 Python、CUDA／CPU、音訊後端、本機模型路徑、llama.cpp 與 "
                "OBS Overlay localhost 連接埠。"
            )
        )
        layout.addWidget(self.doctor_output, 1)
        layout.addWidget(self.doctor_button)
        self.tabs.addTab(page, "診斷")
        self.doctor_button.clicked.connect(self._run_doctor)

    def _build_overlay_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)

        service_box = QGroupBox("OBS Browser Source")
        service_form = QGridLayout(service_box)
        self.overlay_enabled = QCheckBox("啟用 localhost HTTP／WebSocket Overlay")
        self.overlay_enabled.setChecked(self.config.obs_overlay_enabled)
        self.overlay_port = QSpinBox()
        self.overlay_port.setRange(1024, 65535)
        self.overlay_port.setValue(self.config.obs_overlay_port)
        self.overlay_url = QLineEdit()
        self.overlay_url.setReadOnly(True)
        self.overlay_copy = QPushButton("複製網址")
        self.overlay_open = QPushButton("瀏覽器預覽")
        service_form.addWidget(self.overlay_enabled, 0, 0, 1, 4)
        service_form.addWidget(QLabel("localhost port"), 1, 0)
        service_form.addWidget(self.overlay_port, 1, 1)
        service_form.addWidget(QLabel("Browser Source URL"), 2, 0)
        service_form.addWidget(self.overlay_url, 2, 1)
        service_form.addWidget(self.overlay_copy, 2, 2)
        service_form.addWidget(self.overlay_open, 2, 3)
        layout.addWidget(service_box)

        content_box = QGroupBox("字幕內容與樣式")
        content_form = QGridLayout(content_box)
        self.overlay_max_lines = QSpinBox()
        self.overlay_max_lines.setRange(1, 8)
        self.overlay_max_lines.setValue(self.config.obs_overlay_max_lines)
        self.overlay_show_source = QCheckBox("同時顯示來源原文")
        self.overlay_show_source.setChecked(self.config.obs_overlay_show_source)
        self.overlay_font_family = QLineEdit(self.config.obs_overlay_font_family)
        self.overlay_translation_size = QSpinBox()
        self.overlay_translation_size.setRange(16, 120)
        self.overlay_translation_size.setValue(self.config.obs_overlay_translation_size)
        self.overlay_source_size = QSpinBox()
        self.overlay_source_size.setRange(12, 96)
        self.overlay_source_size.setValue(self.config.obs_overlay_source_size)
        self.overlay_text_color = QLineEdit(self.config.obs_overlay_text_color)
        self.overlay_source_color = QLineEdit(self.config.obs_overlay_source_color)
        self.overlay_background = QLineEdit(self.config.obs_overlay_background)
        self.overlay_outline_color = QLineEdit(self.config.obs_overlay_outline_color)
        self.overlay_outline_px = QSpinBox()
        self.overlay_outline_px.setRange(0, 8)
        self.overlay_outline_px.setValue(self.config.obs_overlay_outline_px)
        self.overlay_position = QComboBox()
        for value, label in (("top", "上方"), ("center", "中央"), ("bottom", "下方")):
            self.overlay_position.addItem(label, value)
        self.overlay_position.setCurrentIndex(
            max(0, self.overlay_position.findData(self.config.obs_overlay_position))
        )
        self.overlay_alignment = QComboBox()
        for value, label in (("left", "靠左"), ("center", "置中"), ("right", "靠右")):
            self.overlay_alignment.addItem(label, value)
        self.overlay_alignment.setCurrentIndex(
            max(0, self.overlay_alignment.findData(self.config.obs_overlay_text_align))
        )
        self.overlay_width = QSpinBox()
        self.overlay_width.setRange(25, 100)
        self.overlay_width.setSuffix(" %")
        self.overlay_width.setValue(self.config.obs_overlay_width_percent)

        content_form.addWidget(QLabel("最近顯示句數"), 0, 0)
        content_form.addWidget(self.overlay_max_lines, 0, 1)
        content_form.addWidget(self.overlay_show_source, 0, 2, 1, 2)
        content_form.addWidget(QLabel("字型"), 1, 0)
        content_form.addWidget(self.overlay_font_family, 1, 1, 1, 3)
        content_form.addWidget(QLabel("譯文字級"), 2, 0)
        content_form.addWidget(self.overlay_translation_size, 2, 1)
        content_form.addWidget(QLabel("原文字級"), 2, 2)
        content_form.addWidget(self.overlay_source_size, 2, 3)
        content_form.addWidget(QLabel("譯文顏色"), 3, 0)
        content_form.addWidget(self.overlay_text_color, 3, 1)
        content_form.addWidget(QLabel("原文顏色"), 3, 2)
        content_form.addWidget(self.overlay_source_color, 3, 3)
        content_form.addWidget(QLabel("背景 CSS 顏色"), 4, 0)
        content_form.addWidget(self.overlay_background, 4, 1)
        content_form.addWidget(QLabel("外框顏色／px"), 4, 2)
        outline_row = QHBoxLayout()
        outline_row.addWidget(self.overlay_outline_color)
        outline_row.addWidget(self.overlay_outline_px)
        content_form.addLayout(outline_row, 4, 3)
        content_form.addWidget(QLabel("畫面位置"), 5, 0)
        content_form.addWidget(self.overlay_position, 5, 1)
        content_form.addWidget(QLabel("文字對齊"), 5, 2)
        content_form.addWidget(self.overlay_alignment, 5, 3)
        content_form.addWidget(QLabel("最大寬度"), 6, 0)
        content_form.addWidget(self.overlay_width, 6, 1)
        layout.addWidget(content_box)

        buttons = QHBoxLayout()
        self.overlay_apply = QPushButton("套用／重新啟動")
        self.overlay_preview = QPushButton("送出預覽字幕")
        self.overlay_clear = QPushButton("清除 Overlay")
        buttons.addWidget(self.overlay_apply)
        buttons.addWidget(self.overlay_preview)
        buttons.addWidget(self.overlay_clear)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.overlay_status = QLabel("尚未啟用")
        self.overlay_status.setWordWrap(True)
        layout.addWidget(self.overlay_status)
        note = QLabel(
            "OBS 建議建立 1920×1080 Browser Source，貼上上方網址。服務只綁定 "
            "127.0.0.1；OBS 重新連線後會自動取得目前字幕快照。樣式可在翻譯期間套用。"
            "只顯示單一路時，在網址加 ?route=<即時翻譯頁顯示的 route ID>。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.tabs.addTab(page, "OBS Overlay")

        self.overlay_port.valueChanged.connect(self._refresh_overlay_url)
        self.overlay_copy.clicked.connect(self._copy_overlay_url)
        self.overlay_open.clicked.connect(self._open_overlay_url)
        self.overlay_apply.clicked.connect(self._apply_overlay_settings)
        self.overlay_preview.clicked.connect(self.controller.preview_overlay)
        self.overlay_clear.clicked.connect(self.controller.clear_overlay)
        self._refresh_overlay_url()
        self._overlay_running_changed(False)

    def _connect_controller(self) -> None:
        self.controller.level_changed.connect(self._update_level)
        self.controller.route_level_changed.connect(self._update_route_level)
        self.controller.status_changed.connect(self._set_status)
        self.controller.error_occurred.connect(self._show_error)
        self.controller.segment_changed.connect(self._show_segment)
        self.controller.segments_cleared.connect(self._clear_timeline)
        self.controller.running_changed.connect(lambda _: self._sync_buttons())
        self.controller.settings_locked_changed.connect(self._lock_settings)
        self.controller.overlay_status_changed.connect(self.overlay_status.setText)
        self.controller.overlay_running_changed.connect(self._overlay_running_changed)

    def _initialize_overlay(self) -> None:
        if self.config.obs_overlay_enabled:
            self.controller.configure_overlay()

    def _refresh_overlay_url(self, *_: object) -> None:
        self.overlay_url.setText(
            f"http://127.0.0.1:{self.overlay_port.value()}/overlay"
        )

    def _copy_overlay_url(self) -> None:
        QGuiApplication.clipboard().setText(self.overlay_url.text())
        self.overlay_status.setText("已複製 Browser Source URL")

    def _open_overlay_url(self) -> None:
        QDesktopServices.openUrl(QUrl(self.overlay_url.text()))

    def _read_overlay_widgets(self) -> None:
        self.config.obs_overlay_enabled = self.overlay_enabled.isChecked()
        self.config.obs_overlay_port = self.overlay_port.value()
        self.config.obs_overlay_max_lines = self.overlay_max_lines.value()
        self.config.obs_overlay_show_source = self.overlay_show_source.isChecked()
        self.config.obs_overlay_font_family = (
            self.overlay_font_family.text().strip() or "Microsoft JhengHei"
        )
        self.config.obs_overlay_translation_size = self.overlay_translation_size.value()
        self.config.obs_overlay_source_size = self.overlay_source_size.value()
        self.config.obs_overlay_text_color = self.overlay_text_color.text().strip() or "#FFFFFF"
        self.config.obs_overlay_source_color = (
            self.overlay_source_color.text().strip() or "#D1D5DB"
        )
        self.config.obs_overlay_background = (
            self.overlay_background.text().strip() or "rgba(0, 0, 0, 0.68)"
        )
        self.config.obs_overlay_outline_color = (
            self.overlay_outline_color.text().strip() or "#000000"
        )
        self.config.obs_overlay_outline_px = self.overlay_outline_px.value()
        self.config.obs_overlay_position = str(self.overlay_position.currentData())
        self.config.obs_overlay_text_align = str(self.overlay_alignment.currentData())
        self.config.obs_overlay_width_percent = self.overlay_width.value()

    def _apply_overlay_settings(self) -> None:
        self._read_overlay_widgets()
        save_config(self.config)
        self.controller.configure_overlay()
        self._refresh_overlay_url()

    def _overlay_running_changed(self, running: bool) -> None:
        self.overlay_preview.setEnabled(running)
        self.overlay_clear.setEnabled(running)

    def refresh_sources(self) -> None:
        if self.controller.workers_started:
            return
        self.controller.audio.close()
        try:
            self.sources = list_audio_sources()
            missing: list[str] = []
            routes = {route.id: route for route in self.config.audio_routes}
            for route_id, card in self.route_cards.items():
                route = routes[route_id]
                matched = card.populate_sources(
                    self.sources, route.source_fingerprint
                )
                if route.source_fingerprint and not matched:
                    missing.append(route.label)
            if missing:
                self._set_status(
                    "先前選定的音訊來源目前不存在："
                    + "、".join(missing)
                    + "；不會自動改用預設麥克風"
                )
        except Exception as exc:
            self.sources = []
            self._set_status(f"列出音訊來源失敗：{exc}")

    def _create_route_card(self, route: AudioRouteConfig) -> None:
        card = AudioRouteCard(
            route,
            self._route_device_selected,
            self.controller.set_route_gain_db,
            self.controller.set_route_threshold,
            self._remove_route,
        )
        self.route_cards[route.id] = card
        self.routes_layout.addWidget(card)
        if len(self.route_cards) == 1:
            self._set_legacy_route_aliases(card)

    def _set_legacy_route_aliases(self, card: AudioRouteCard) -> None:
        # Compatibility aliases for integrations that used the original single-route GUI.
        self.source_combo = card.language_combo
        self.device_combo = card.device_combo
        self.gain_slider = card.gain_slider
        self.level = card.level
        self.threshold_slider = card.threshold_slider

    def _add_route(self) -> None:
        route = AudioRouteConfig(
            id=f"route-{uuid.uuid4().hex[:8]}",
            label=f"音訊來源 {len(self.route_cards) + 1}",
        )
        self.config.audio_routes.append(route)
        self._create_route_card(route)
        self.route_cards[route.id].populate_sources(self.sources, "")

    def _remove_route(self, route_id: str) -> None:
        if self.controller.workers_started or len(self.route_cards) <= 1:
            if len(self.route_cards) <= 1:
                self._show_error("至少保留一個音訊來源")
            return
        self.controller.close_route(route_id)
        card = self.route_cards.pop(route_id)
        self.routes_layout.removeWidget(card)
        card.deleteLater()
        self.config.audio_routes = [
            route for route in self.config.audio_routes if route.id != route_id
        ]
        self._set_legacy_route_aliases(next(iter(self.route_cards.values())))
        save_config(self.config)

    def _route_device_selected(self, route_id: str, source: object) -> None:
        if self.controller.workers_started:
            return
        self.controller.close_route(route_id)
        if not isinstance(source, AudioSource):
            return
        route = next(
            route for route in self.config.audio_routes if route.id == route_id
        )
        card = self.route_cards[route_id]
        current = card.route_config()
        route.label = current.label
        route.source_language = current.source_language
        route.gain_db = current.gain_db
        route.threshold = current.threshold
        route.enabled = current.enabled
        self.controller.monitor_route(route_id, source)
        save_config(self.config)

    def _target_changed(self, *_: object) -> None:
        custom = self.target_combo.currentData() == "__custom__"
        for widget in (
            self.custom_target_code,
            self.custom_target_name,
            self.custom_target_instruction,
        ):
            widget.setVisible(custom)

    def _read_widgets(self) -> bool:
        existing_routes = {route.id: route for route in self.config.audio_routes}
        updated_routes: list[AudioRouteConfig] = []
        for card in self.route_cards.values():
            current = card.route_config()
            route = existing_routes.get(current.id, current)
            route.label = current.label
            route.source_fingerprint = current.source_fingerprint
            route.source_language = current.source_language
            route.gain_db = current.gain_db
            route.threshold = current.threshold
            route.enabled = current.enabled
            updated_routes.append(route)
        # Preserve route object identity. Open AudioEngine instances retain these
        # objects while a stopped session is reconfigured and started again.
        self.config.audio_routes = updated_routes
        first_route = self.config.audio_routes[0]
        self.config.source_language = first_route.source_language
        self.config.audio_source_fingerprint = first_route.source_fingerprint
        self.config.input_gain_db = round(first_route.gain_db)
        self.config.input_threshold = first_route.threshold
        target_code = str(self.target_combo.currentData())
        if target_code == "__custom__":
            code = self.custom_target_code.text().strip()
            name = self.custom_target_name.text().strip()
            if not code or not name:
                self._show_error("自訂目標語言必須填寫代碼與顯示名稱")
                return False
            self.config.target_language_code = code
            self.config.target_language_name = name
            self.config.target_language_instruction = (
                self.custom_target_instruction.text().strip()
            )
        else:
            spec = TARGET_LANGUAGES[target_code]
            self.config.target_language_code = spec.code
            self.config.target_language_name = spec.display_name
            self.config.target_language_instruction = spec.instruction
        self.config.whisper_model_path = self.whisper_path.text().strip()
        self.config.whisper_device = str(self.compute_combo.currentData())
        self.config.whisper_compute_type = "auto"
        self.config.llama_server_path = self.llama_path.text().strip()
        self.config.llama_model_path = self.gguf_path.text().strip()
        self.config.llama_gpu_layers = self.gpu_layers.value()
        self.config.llama_context = self.context_size.value()
        self.config.llama_port = self.port.value()
        self.config.revision_window = self.revision_window.value()
        self.config.finalization_seconds = self.finalization_seconds.value()
        return True

    def _start_clicked(self) -> None:
        if self.controller.workers_started:
            self.controller.resume()
            return
        if not self._read_widgets():
            return
        save_config(self.config)
        self.controller.start()

    def _lock_settings(self, locked: bool) -> None:
        for widget in (
            self.target_combo,
            self.custom_target_code,
            self.custom_target_name,
            self.custom_target_instruction,
            self.refresh_button,
            self.add_route_button,
            self.whisper_path,
            self.whisper_browse,
            self.whisper_detect,
            self.whisper_use_detected,
            self.whisper_model_choice,
            self.whisper_download,
            self.llama_path,
            self.llama_browse,
            self.gguf_path,
            self.gguf_browse,
            self.compute_combo,
            self.gpu_layers,
            self.context_size,
            self.port,
            self.revision_window,
            self.finalization_seconds,
        ):
            widget.setEnabled(not locked)
        for card in self.route_cards.values():
            card.set_locked(locked)
        if not locked:
            self._target_changed()
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        running = self.controller.running
        workers = self.controller.workers_started
        self.start_button.setText("繼續" if workers and not running else "開始")
        self.start_button.setEnabled(not running)
        self.pause_button.setEnabled(running)
        self.stop_button.setEnabled(workers)
        self.clear_button.setEnabled(not workers)

    def _show_segment(self, value: object) -> None:
        if not isinstance(value, TranscriptSegment):
            return
        existing = self.segment_items.get(value.id)
        if existing:
            item, card = existing
            card.update_segment(value)
            item.setSizeHint(card.sizeHint())
            return
        item = QListWidgetItem()
        card = SegmentCard(value)
        item.setSizeHint(card.sizeHint())
        self.timeline.addItem(item)
        self.timeline.setItemWidget(item, card)
        self.segment_items[value.id] = (item, card)
        self.timeline.scrollToBottom()

    def _clear_timeline(self) -> None:
        self.timeline.clear()
        self.segment_items.clear()

    def _gain_changed(self, value: int) -> None:
        self.gain_value.setText(f"+{value} dB")
        self.controller.set_input_gain_db(value)

    def _threshold_changed(self, value: int) -> None:
        threshold = meter_value_to_threshold(value)
        self.threshold_value.setText(f"{value / 10:.1f}% / RMS {threshold:.4f}")
        self.controller.set_input_threshold(threshold)

    def _update_level(self, level: float) -> None:
        first = next(iter(self.route_cards.values()), None)
        if first:
            first.level.setValue(round(level * 1000))

    def _update_route_level(self, route_id: str, level: float) -> None:
        card = self.route_cards.get(route_id)
        if card:
            card.level.setValue(round(level * 1000))

    def _set_status(self, message: str) -> None:
        self.status.setText(message)
        if hasattr(self, "doctor_output"):
            self.doctor_output.appendPlainText(message)

    def _show_error(self, message: str) -> None:
        self._set_status(message)
        if self.isVisible() and not self._closing:
            QMessageBox.warning(self, "Context Live Translator", message)

    def _browse_whisper(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "選擇本機 Whisper CTranslate2 模型目錄",
            self.whisper_path.text(),
        )
        if directory:
            self.whisper_path.setText(directory)
            validation = validate_whisper_model(directory)
            self.whisper_download_status.setText(validation.message)

    def _detect_whisper_models(self) -> None:
        current = self.whisper_path.text().strip()
        models = discover_whisper_models()
        self.whisper_detected.clear()
        for model in models:
            origin = "管理位置" if model.origin == "managed" else "Hugging Face cache"
            size_mb = model.total_bytes / 1_000_000
            self.whisper_detected.addItem(
                f"{model.key} · {origin} · {size_mb:.0f} MB",
                str(model.path),
            )
        current_valid = validate_whisper_model(current).valid
        if models and not current_valid:
            self.whisper_path.setText(str(models[0].path))
            self.config.whisper_model_path = str(models[0].path)
            self.whisper_download_status.setText(
                f"已自動採用偵測到的既有模型：{models[0].path}"
            )
        elif models:
            self.whisper_download_status.setText(
                f"找到 {len(models)} 個可用模型；目前設定有效。"
            )
        else:
            self.whisper_download_status.setText(
                "未找到完整模型；可選擇本機目錄，或明確按下下載。"
            )
        self.whisper_use_detected.setEnabled(bool(models))

    def _use_detected_whisper(self) -> None:
        path = self.whisper_detected.currentData()
        if path:
            self.whisper_path.setText(str(path))
            self.config.whisper_model_path = str(path)
            save_config(self.config)
            self.whisper_download_status.setText(f"已選用：{path}")

    def _start_whisper_download(self) -> None:
        if self._download_thread and self._download_thread.isRunning():
            return
        key = str(self.whisper_model_choice.currentData())
        spec = WHISPER_MODELS[key]
        size_mb = spec.approximate_bytes / 1_000_000
        destination = managed_whisper_path(key)
        disk_probe = destination.parent
        while not disk_probe.exists() and disk_probe != disk_probe.parent:
            disk_probe = disk_probe.parent
        free_mb = shutil.disk_usage(disk_probe).free / 1_000_000
        answer = QMessageBox.question(
            self,
            "下載 Whisper 模型",
            f"來源：Hugging Face / {spec.repo_id}\n"
            f"大小：約 {size_mb:.0f} MB；磁碟可用：約 {free_mb:.0f} MB\n"
            f"目的地：{destination}\n\n"
            "small 建議即時使用；CPU 模式不保證即時。請先確認模型頁授權與來源。"
            "是否繼續？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        thread = ModelDownloadThread(key, self)
        self._download_thread = thread
        thread.progress.connect(self._download_progress)
        thread.completed.connect(self._download_completed)
        thread.failed.connect(self._download_failed)
        thread.cancelled.connect(self._download_cancelled)
        thread.finished.connect(self._download_finished)
        self._set_download_busy(True)
        thread.start()

    def _cancel_whisper_download(self) -> None:
        if self._download_thread:
            self._download_thread.cancel()
            self.whisper_download_status.setText("正在取消；目前檔案完成後會停止…")

    def _download_progress(self, percent: int, message: str) -> None:
        self.whisper_progress.setValue(percent)
        self.whisper_download_status.setText(message)

    def _download_completed(self, path: str) -> None:
        self.whisper_progress.setValue(100)
        self.whisper_path.setText(path)
        self.config.whisper_model_path = path
        save_config(self.config)
        self.whisper_download_status.setText(f"模型安裝完成：{path}")
        self._detect_whisper_models()

    def _download_failed(self, message: str) -> None:
        self.whisper_download_status.setText(f"模型下載失敗：{message}")
        self._show_error(f"Whisper 模型下載失敗：{message}")

    def _download_cancelled(self) -> None:
        self.whisper_progress.setValue(0)
        self.whisper_download_status.setText(
            "模型下載已取消；暫存檔保留，下次下載可續用。"
        )

    def _download_finished(self) -> None:
        self._set_download_busy(False)
        self._download_thread = None
        if self._close_after_download:
            QTimer.singleShot(0, self.close)

    def _set_download_busy(self, busy: bool) -> None:
        self.whisper_download.setEnabled(not busy)
        self.whisper_cancel.setEnabled(busy)
        self.whisper_model_choice.setEnabled(not busy)
        self.whisper_detect.setEnabled(not busy)
        self.whisper_use_detected.setEnabled(
            not busy and self.whisper_detected.count() > 0
        )

    def _browse_file(self, target: QLineEdit, filter_text: str) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "選擇本機檔案",
            target.text(),
            filter_text,
        )
        if filename:
            target.setText(filename)

    def _run_doctor(self) -> None:
        if not self._read_widgets():
            return
        save_config(self.config)
        self.doctor_output.setPlainText(format_checks(run_doctor(self.config)))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._download_thread and self._download_thread.isRunning():
            self._close_after_download = True
            self._cancel_whisper_download()
            event.ignore()
            return
        self._closing = True
        if self._read_widgets():
            save_config(self.config)
        self.controller.shutdown()
        event.accept()
