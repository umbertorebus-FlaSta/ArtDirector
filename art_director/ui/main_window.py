"""Main configuration and live stage monitor window for Art Director."""

from __future__ import annotations

import copy
import threading
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QCursor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..audio.devices import list_input_devices
from ..audio.input_stream import AudioCaptureService
from ..config.manager import export_config_file, get_configs_dir, get_samples_dir
from ..core.controller import ArtDirectorController
from ..os_layer.hotkeys import format_hotkey_display
from .program_wizard import AddProgramWizardDialog
from .settings_dialog import (
    HotkeyCaptureDialog,
    LoadConfigProfileDialog,
    SaveConfigProfileDialog,
    SettingsDialog,
    SystemSettingsPanel,
)
from .tray import ArtDirectorTray
from .widgets import DARK_STYLESHEET, AudioLevelMeter


class _UiEventBridge(QObject):
    """Marshals background EventBus events safely onto the Qt main UI thread."""

    mode_changed = Signal(str, str, str)
    audio_level = Signal(float, float, bool)
    stt_status = Signal(str, bool, str)
    stt_transcript = Signal(str, bool, float, str)
    log_message = Signal(str, str)
    mic_test_done = Signal(bool, str)
    config_switched = Signal()


class MainWindow(QMainWindow):
    """Art Director configuration GUI & live diagnostic dashboard."""

    def __init__(self, controller: ArtDirectorController, start_hidden: bool = False) -> None:
        super().__init__()
        self.controller = controller
        self._force_quit = False
        self.setWindowTitle("Art Director — Offline Voice Stage Controller")
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(
                max(960, min(1280, int(avail.width() * 0.94))),
                max(640, min(840, int(avail.height() * 0.90))),
            )
        else:
            self.resize(1200, 780)
        self.setStyleSheet(DARK_STYLESHEET)

        self._bridge = _UiEventBridge(self)
        self._bridge.mode_changed.connect(self._on_mode_changed_ui)
        self._bridge.audio_level.connect(self._on_audio_level_ui)
        self._bridge.stt_status.connect(self._on_stt_status_ui)
        self._bridge.stt_transcript.connect(self._on_stt_transcript_ui)
        self._bridge.log_message.connect(self._append_log_ui)
        self._bridge.mic_test_done.connect(self._on_mic_test_done_ui)
        self._bridge.config_switched.connect(self._on_external_config_switched)

        self._tray = ArtDirectorTray(
            controller=self.controller,
            on_show_window=self.restore_from_tray,
            on_quit_app=self.quit_completely,
            on_config_switched=lambda _name: self._bridge.config_switched.emit(),
            parent=self,
        )
        self._tray.show()

        self._build_ui()
        self._subscribe_events()
        self._sync_ui_from_config()

        if start_hidden or self.controller.config.general.start_minimized_to_tray:
            self.hide()
        else:
            self.show()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)
        root.setContentsMargins(12, 10, 12, 12)

        # ---- Top Menu & Quick Action Strip (File | + Aggiungi Programma verde | Setup attivo)
        menu_strip = QHBoxLayout()
        menu_strip.setSpacing(6)

        self.file_btn = QToolButton()
        self.file_btn.setText("📁 File ▾")
        self.file_btn.setMinimumHeight(34)
        self.file_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.file_btn.setStyleSheet(
            "QToolButton { background-color: #1f2633; border: 1px solid #384357; border-radius: 6px; padding: 6px 14px; font-weight: 700; color: #e6eaf2; }"
            "QToolButton:hover { background-color: #293244; }"
            "QToolButton::menu-indicator { image: none; width: 0px; }"
        )
        self.file_menu = QMenu(self)
        act_load = QAction("📂 Carica Configurazione / Preset...", self.file_menu)
        act_load.triggered.connect(self._on_load_config)
        act_save = QAction("💾 Salva Configurazione / Profilo...", self.file_menu)
        act_save.triggered.connect(self._on_save_config)
        act_open_cfg = QAction("📁 Apri Cartella 'configurazioni/'", self.file_menu)
        act_open_cfg.triggered.connect(self._open_configs_folder)
        act_open_smp = QAction("🔊 Apri Cartella 'campioni/'", self.file_menu)
        act_open_smp.triggered.connect(self._open_samples_folder)
        act_quit = QAction("❌ Esci da Art Director", self.file_menu)
        act_quit.triggered.connect(self.quit_completely)
        self.file_menu.addAction(act_load)
        self.file_menu.addAction(act_save)
        self.file_menu.addSeparator()
        self.file_menu.addAction(act_open_cfg)
        self.file_menu.addAction(act_open_smp)
        self.file_menu.addSeparator()
        self.file_menu.addAction(act_quit)
        self.file_btn.setMenu(self.file_menu)
        menu_strip.addWidget(self.file_btn)

        self.add_prog_btn = QPushButton("➕ Aggiungi Programma")
        self.add_prog_btn.setMinimumHeight(34)
        self.add_prog_btn.setToolTip(
            "Aggiungi subito un nuovo programma da pilotare (Wizard Passo 1-2-3)"
        )
        self.add_prog_btn.setStyleSheet(
            "QPushButton { background-color: #15803d; border: 1px solid #22c55e; color: white; font-weight: 800; padding: 6px 16px; border-radius: 6px; }"
            "QPushButton:hover { background-color: #16a34a; }"
        )
        self.add_prog_btn.clicked.connect(self._on_add_program_direct)
        menu_strip.addWidget(self.add_prog_btn)

        menu_strip.addStretch(1)
        self.active_profile_label = QLabel("Setup attivo: <b>Predefinito (config.json)</b>")
        self.active_profile_label.setStyleSheet("color: #93c5fd;")
        menu_strip.addWidget(self.active_profile_label)
        root.addLayout(menu_strip)

        # ---- Top Actions Header (App/Settings al posto di WakeMode + Sleep/Wake + App Palco + Popup + PANIC)
        top_row = QHBoxLayout()

        self.settings_btn = QPushButton("📱 App / Settings")
        self.settings_btn.setMinimumHeight(48)
        self.settings_btn.setToolTip(
            "Secondo layer: gestisci esclusivamente le Applicazioni da pilotare"
        )
        self.settings_btn.setStyleSheet(
            "QPushButton { background-color: #1e3a8a; border: 1px solid #3b82f6; color: white; font-size: 13px; font-weight: 700; padding: 6px 14px; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        self.settings_btn.clicked.connect(self.open_settings)
        top_row.addWidget(self.settings_btn)

        mode_pair = QHBoxLayout()
        mode_pair.setSpacing(2)
        self.toggle_mode_btn = QPushButton("👍 WAKE MODE · Sleep / Wake")
        self.toggle_mode_btn.setMinimumHeight(48)
        self.toggle_mode_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.toggle_mode_btn.customContextMenuRequested.connect(
            lambda _pos: self._open_mode_shortcut_menu()
        )
        self.toggle_mode_btn.clicked.connect(
            lambda: self.controller.toggle_sleep_wake(source="ui")
        )
        self.mode_shortcut_btn = QPushButton("⌨️")
        self.mode_shortcut_btn.setFixedWidth(36)
        self.mode_shortcut_btn.setMinimumHeight(48)
        self.mode_shortcut_btn.setToolTip(
            "Assegna Shortcut da tastiera a Sleep/Wake o Push-to-Talk"
        )
        self.mode_shortcut_btn.clicked.connect(self._open_mode_shortcut_menu)
        mode_pair.addWidget(self.toggle_mode_btn, stretch=1)
        mode_pair.addWidget(self.mode_shortcut_btn)
        top_row.addLayout(mode_pair, stretch=2)

        self.launch_apps_btn = QPushButton("🚀 Avvia App Palco")
        self.launch_apps_btn.setMinimumHeight(48)
        self.launch_apps_btn.clicked.connect(self.controller.launch_stage_apps_now)
        top_row.addWidget(self.launch_apps_btn)

        self.popup_btn = QPushButton("🪟 Chiudi Pop-up")
        self.popup_btn.setMinimumHeight(48)
        self.popup_btn.clicked.connect(
            lambda: self.controller.process_text_command(
                self.controller.config.popup_handler.voice_triggers[0]
                if self.controller.config.popup_handler.voice_triggers
                else "chiudi avviso",
                source="ui_button",
            )
        )
        top_row.addWidget(self.popup_btn)

        panic_pair = QHBoxLayout()
        panic_pair.setSpacing(2)
        self.panic_btn = QPushButton("🚨 PANIC / EMERGENCY")
        self.panic_btn.setMinimumHeight(48)
        self.panic_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.panic_btn.customContextMenuRequested.connect(
            lambda _pos: self._open_panic_shortcut_menu()
        )
        self.panic_btn.clicked.connect(
            lambda: self.controller.trigger_panic(source="ui_button")
        )
        self.panic_shortcut_btn = QPushButton("⌨️")
        self.panic_shortcut_btn.setFixedWidth(36)
        self.panic_shortcut_btn.setMinimumHeight(48)
        self.panic_shortcut_btn.setToolTip(
            "Assegna o cambia Shortcut tastiera per PANIC / EMERGENCY"
        )
        self.panic_shortcut_btn.clicked.connect(
            lambda: self._assign_hotkey_role("panic")
        )
        panic_pair.addWidget(self.panic_btn)
        panic_pair.addWidget(self.panic_shortcut_btn)
        top_row.addLayout(panic_pair)

        root.addLayout(top_row)

        # ---- Audio & Anti-Feedback Panel
        audio_box = QGroupBox("Microfono Dedicato & Prevenzione Loop Acustici (100% Offline)")
        audio_layout = QVBoxLayout(audio_box)

        mic_row = QHBoxLayout()
        self.mic_combo = QComboBox()
        self.mic_refresh_btn = QPushButton("Aggiorna Mic")
        self.mic_refresh_btn.clicked.connect(self._refresh_mics)
        self.mic_apply_btn = QPushButton("Usa Selezionato")
        self.mic_apply_btn.clicked.connect(self._apply_selected_mic)
        self.mic_test_btn = QPushButton("🎙️ Testa Microfono (2s)")
        self.mic_test_btn.clicked.connect(self._run_mic_test)

        mic_row.addWidget(QLabel("Ingresso:"))
        mic_row.addWidget(self.mic_combo, stretch=1)
        mic_row.addWidget(self.mic_refresh_btn)
        mic_row.addWidget(self.mic_apply_btn)
        mic_row.addWidget(self.mic_test_btn)
        audio_layout.addLayout(mic_row)

        meter_row = QHBoxLayout()
        self.vu_meter = AudioLevelMeter()
        self.level_label = QLabel("-90.0 dBFS")
        self.level_label.setMinimumWidth(85)

        self.gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(2, 50)  # 0.2x .. 5.0x
        self.gain_slider.setMaximumWidth(130)
        self.gain_slider.valueChanged.connect(self._on_gain_slider_changed)
        self.gain_val_label = QLabel("Gain: 1.0x")
        self.gain_val_label.setMinimumWidth(75)

        self.gate_slider = QSlider(Qt.Orientation.Horizontal)
        self.gate_slider.setRange(-85, -10)
        self.gate_slider.setMaximumWidth(130)
        self.gate_slider.valueChanged.connect(self._on_gate_slider_changed)
        self.gate_val_label = QLabel("Gate: -42 dB")
        self.gate_val_label.setMinimumWidth(82)

        meter_row.addWidget(QLabel("Livello:"))
        meter_row.addWidget(self.vu_meter, stretch=1)
        meter_row.addWidget(self.level_label)
        meter_row.addWidget(self.gain_val_label)
        meter_row.addWidget(self.gain_slider)
        meter_row.addWidget(self.gate_val_label)
        meter_row.addWidget(self.gate_slider)
        audio_layout.addLayout(meter_row)

        self.stt_status_label = QLabel("STT Offline: inizializzazione...")
        self.stt_status_label.setStyleSheet("color: #9fb3d9;")
        audio_layout.addWidget(self.stt_status_label)
        root.addWidget(audio_box)

        # ---- Active Dynamic Programs Overview (managed in App / Settings or added via + Aggiungi Programma)
        prefix_box = QGroupBox("Applicazioni & Comandi Configurati (Gestiti in 📱 App / Settings)")
        prefix_layout = QVBoxLayout(prefix_box)
        self.prefix_summary_label = QLabel()
        self.prefix_summary_label.setWordWrap(True)
        self.prefix_summary_label.setStyleSheet("color: #cdd8ed;")
        prefix_layout.addWidget(self.prefix_summary_label)
        root.addWidget(prefix_box)

        # ---- Voice Transcript / Test Command Bar
        sim_box = QGroupBox("Test Rapido & Simulatore Comandi Vocali")
        sim_row = QHBoxLayout(sim_box)
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText(
            "Es: 'UehBerì voce fader 75' | 'UehSonà apri progetto intro' | 'UehMà strobo on' | 'Dormi' | 'Sveglia' | 'Avvia tutto'"
        )
        self.cmd_input.returnPressed.connect(self._send_simulated_command)
        send_btn = QPushButton("Esegui Comando")
        send_btn.clicked.connect(self._send_simulated_command)
        sim_row.addWidget(self.cmd_input, stretch=1)
        sim_row.addWidget(send_btn)
        root.addWidget(sim_box)

        # ---- Bottom Workspace Splitter: Log (Left) | 4 System Settings Tabs (Right)
        bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        bottom_splitter.setChildrenCollapsible(False)

        log_box = QGroupBox("Log Eventi & Esecuzione Real-Time")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        log_layout.addWidget(self.log_view)
        bottom_splitter.addWidget(log_box)

        sys_box = QGroupBox("Impostazioni Sistema Art Director")
        sys_layout = QVBoxLayout(sys_box)
        sys_layout.setContentsMargins(6, 12, 6, 6)
        self.system_panel = SystemSettingsPanel(
            controller=self.controller,
            on_load_config=self._on_load_config,
            on_save_config_as=self._on_save_config,
            on_settings_saved=self._on_system_settings_saved,
            show_save_bar=True,
            parent=self,
        )
        self.system_tabs = self.system_panel.tabs
        sys_layout.addWidget(self.system_panel)
        bottom_splitter.addWidget(sys_box)
        bottom_splitter.setStretchFactor(0, 4)
        bottom_splitter.setStretchFactor(1, 6)
        bottom_splitter.setSizes([460, 700])
        root.addWidget(bottom_splitter, stretch=1)

    def _subscribe_events(self) -> None:
        bus = self.controller.bus
        bus.subscribe(
            "mode_changed",
            lambda ev: self._bridge.mode_changed.emit(
                str(ev.payload.get("mode", "wake")),
                str(ev.payload.get("emoji", "👍")),
                str(ev.payload.get("label", "WAKE MODE")),
            ),
        )
        bus.subscribe(
            "audio_level",
            lambda ev: self._bridge.audio_level.emit(
                float(ev.payload.get("rms_db", -90.0)),
                float(ev.payload.get("peak_db", -90.0)),
                bool(ev.payload.get("gate_open", False)),
            ),
        )
        bus.subscribe(
            "stt_status",
            lambda ev: self._bridge.stt_status.emit(
                str(ev.payload.get("engine", "")),
                bool(ev.payload.get("loaded", False)),
                str(ev.payload.get("message", "")),
            ),
        )
        bus.subscribe(
            "stt_transcript",
            lambda ev: self._bridge.stt_transcript.emit(
                str(ev.payload.get("text", "")),
                bool(ev.payload.get("is_final", True)),
                float(ev.payload.get("latency_ms", 0.0)),
                str(ev.payload.get("engine", "")),
            ),
        )
        bus.subscribe(
            "log",
            lambda ev: self._bridge.log_message.emit(
                str(ev.payload.get("level", "info")),
                str(ev.payload.get("message", "")),
            ),
        )
        bus.subscribe(
            "command_ignored",
            lambda ev: self._bridge.log_message.emit(
                "warning",
                f"Comando non riconosciuto (o Sleep Mode attiva): '{ev.payload.get('text', '')}'"
                if ev.payload.get("sleeping")
                else f"Nessun prefisso/comando riconosciuto in: '{ev.payload.get('text', '')}'",
            ),
        )
        bus.subscribe(
            "audio_error",
            lambda ev: self._bridge.log_message.emit(
                "error", str(ev.payload.get("message", "Errore audio"))
            ),
        )

    def _hotkey_role_meta(self, role: str) -> tuple[str, str]:
        sw = self.controller.config.sleep_wake
        if role == "sleep_wake":
            return "Sleep / Wake Mode", sw.toggle_hotkey
        if role == "ptt":
            return "Push-to-Talk (Microfono)", sw.ptt_hotkey
        return "PANIC / EMERGENCY", self.controller.config.panic.hotkey

    def _other_hotkeys_for(self, role: str) -> dict[str, str]:
        roles = ("sleep_wake", "ptt", "panic")
        out: dict[str, str] = {}
        for r in roles:
            if r == role:
                continue
            label, val = self._hotkey_role_meta(r)
            if val.strip():
                out[label] = val
        return out

    def _apply_hotkey_role(self, role: str, hotkey: str) -> None:
        clean = hotkey.strip()

        def _update(cfg):
            if role == "sleep_wake":
                cfg.sleep_wake.toggle_hotkey = clean
            elif role == "ptt":
                cfg.sleep_wake.ptt_hotkey = clean
            elif role == "panic":
                cfg.panic.hotkey = clean

        self.controller.config_manager.update(_update)
        if hasattr(self, "system_panel"):
            target_edit = {
                "sleep_wake": self.system_panel.sw_hotkey_edit,
                "ptt": self.system_panel.ptt_hotkey_edit,
                "ptt_hotkey": self.system_panel.ptt_hotkey_edit,
                "panic": self.system_panel.panic_hotkey_edit,
            }.get(role)
            if target_edit is not None:
                target_edit.setText(clean)
        self._apply_mode_button_style(
            self.controller.state.mode.value,
            self.controller.state.emoji,
            self.controller.state.label,
        )
        label, _ = self._hotkey_role_meta(role)
        disp = format_hotkey_display(clean)
        if disp:
            self._append_log_ui("info", f"⌨️ Shortcut '{label}' impostata: {disp} ({clean})")
        else:
            self._append_log_ui("info", f"⌨️ Shortcut '{label}' rimossa.")

    def _assign_hotkey_role(self, role: str) -> None:
        label, current = self._hotkey_role_meta(role)
        dlg = HotkeyCaptureDialog(
            action_title=label,
            current_hotkey=current,
            other_hotkeys=self._other_hotkeys_for(role),
            controller=self.controller,
            parent=self,
        )
        if dlg.exec():
            self._apply_hotkey_role(role, dlg.captured_hotkey)

    def _open_mode_shortcut_menu(self) -> None:
        menu = QMenu(self)
        sw_disp = format_hotkey_display(self.controller.config.sleep_wake.toggle_hotkey)
        ptt_disp = format_hotkey_display(self.controller.config.sleep_wake.ptt_hotkey)

        act_sw = menu.addAction(
            f"⌨️ Assegna Shortcut Sleep/Wake...  ({sw_disp or 'nessuna'})"
        )
        act_sw.triggered.connect(lambda: self._assign_hotkey_role("sleep_wake"))

        act_ptt = menu.addAction(
            f"🎙️ Assegna Push-to-Talk (tieni premuto)...  ({ptt_disp or 'disattivo'})"
        )
        act_ptt.triggered.connect(lambda: self._assign_hotkey_role("ptt"))

        if sw_disp or ptt_disp:
            menu.addSeparator()
        if sw_disp:
            act_clr_sw = menu.addAction(f"🗑️ Rimuovi Shortcut Sleep/Wake ({sw_disp})")
            act_clr_sw.triggered.connect(lambda: self._apply_hotkey_role("sleep_wake", ""))
        if ptt_disp:
            act_clr_ptt = menu.addAction(f"🗑️ Rimuovi Push-to-Talk ({ptt_disp})")
            act_clr_ptt.triggered.connect(lambda: self._apply_hotkey_role("ptt", ""))

        menu.addSeparator()
        act_tab = menu.addAction("⚙️ Apri tab 'Sleep / Wake & Panic'")
        act_tab.triggered.connect(lambda: self.system_tabs.setCurrentIndex(1))
        menu.exec(QCursor.pos())

    def _open_panic_shortcut_menu(self) -> None:
        menu = QMenu(self)
        p_disp = format_hotkey_display(self.controller.config.panic.hotkey)
        act_p = menu.addAction(
            f"⌨️ Assegna Shortcut PANIC...  ({p_disp or 'nessuna'})"
        )
        act_p.triggered.connect(lambda: self._assign_hotkey_role("panic"))
        if p_disp:
            act_clr = menu.addAction(f"🗑️ Rimuovi Shortcut PANIC ({p_disp})")
            act_clr.triggered.connect(lambda: self._apply_hotkey_role("panic", ""))
        menu.addSeparator()
        act_tab = menu.addAction("⚙️ Apri tab 'Sleep / Wake & Panic'")
        act_tab.triggered.connect(lambda: self.system_tabs.setCurrentIndex(1))
        menu.exec(QCursor.pos())

    def _apply_mode_button_style(self, mode: str, emoji: str, label: str) -> None:
        m = (mode or "wake").lower()
        if m == "sleep":
            bg, border, action_hint = "#451a03", "#f59e0b", "Clicca per Wake"
        elif m == "panic":
            bg, border, action_hint = "#7f1d1d", "#ef4444", "Emergenza attiva"
        else:
            bg, border, action_hint = "#14532d", "#22c55e", "Clicca per Sleep"

        sw = self.controller.config.sleep_wake
        sw_disp = format_hotkey_display(sw.toggle_hotkey)
        ptt_disp = format_hotkey_display(sw.ptt_hotkey)
        badges: list[str] = []
        if sw_disp:
            badges.append(f"[{sw_disp}]")
        if ptt_disp:
            badges.append(f"[PTT: {ptt_disp}]")
        badge_str = f"  {' '.join(badges)}" if badges else ""

        self.toggle_mode_btn.setText(f"{emoji} {label}  ·  {action_hint}{badge_str}")
        self.toggle_mode_btn.setToolTip(
            f"Stato attuale: {label}\n"
            f"Shortcut Sleep/Wake: {sw_disp or 'Non impostata'}\n"
            f"Push-to-Talk: {ptt_disp or 'Disattivato'}\n"
            "Click sinistro: alterna Sleep/Wake · Click destro o '⌨️': assegna shortcut"
        )
        self.toggle_mode_btn.setStyleSheet(
            f"QPushButton {{ background-color: {bg}; border: 2px solid {border}; color: white; font-size: 13px; font-weight: 800; padding: 6px 12px; border-radius: 6px; }}"
            f"QPushButton:hover {{ border-color: #ffffff; }}"
        )
        self.mode_shortcut_btn.setStyleSheet(
            f"QPushButton {{ background-color: {bg}; border: 2px solid {border}; color: white; font-size: 14px; border-radius: 6px; padding: 0px; }}"
            f"QPushButton:hover {{ border-color: #ffffff; }}"
        )

        p_disp = format_hotkey_display(self.controller.config.panic.hotkey)
        p_badge = f"  [{p_disp}]" if p_disp else ""
        self.panic_btn.setText(f"🚨 PANIC / EMERGENCY{p_badge}")
        self.panic_btn.setToolTip(
            f"Interrompe subito macro e comandi di palco\n"
            f"Shortcut PANIC: {p_disp or 'Non impostata'}\n"
            "Click destro o '⌨️': assegna o cambia shortcut"
        )
        self.panic_btn.setStyleSheet(
            "QPushButton { background-color: #b91c1c; border: 2px solid #ef4444; color: white; font-size: 14px; font-weight: 800; padding: 6px 12px; border-radius: 6px; }"
            "QPushButton:hover { background-color: #dc2626; border-color: #ffffff; }"
        )
        self.panic_shortcut_btn.setStyleSheet(
            "QPushButton { background-color: #b91c1c; border: 2px solid #ef4444; color: white; font-size: 14px; border-radius: 6px; padding: 0px; }"
            "QPushButton:hover { background-color: #dc2626; border-color: #ffffff; }"
        )

    def _on_external_config_switched(self) -> None:
        self._sync_ui_from_config(refresh_system_tabs=True)

    def _on_system_settings_saved(self) -> None:
        self._sync_ui_from_config(refresh_system_tabs=False)
        self._append_log_ui("info", "Impostazioni di sistema salvate e applicate.")

    def _refresh_program_summary(self) -> None:
        cfg = self.controller.config
        active_name = cfg.general.active_profile_name.strip() or "Predefinito (config.json)"
        self.active_profile_label.setText(f"Setup attivo: <b>{active_name}</b>")

        lines: list[str] = []
        if cfg.programs:
            for prog in cfg.programs:
                status = "ON" if prog.enabled else "OFF"
                cmds = ", ".join(prog.open_commands) or "(nessun comando apertura)"
                prog_samples = len(prog.open_samples) + sum(
                    len(fn.sample_files) for fn in prog.functions
                )
                lines.append(
                    f"• <b>{prog.name}</b> [{status}] — Apertura/Prefissi: {cmds} "
                    f"(<i>{len(prog.functions)} funzioni/macro · 🔊 {prog_samples} campioni</i>)"
                )
        else:
            lines.append(
                "Nessun programma ancora aggiunto. Premi <b>➕ Aggiungi Programma</b> in alto "
                "oppure apri <b>📱 App / Settings</b> per configurare le tue app."
            )
        total_samples = self.controller.stt.sample_library.count
        lines.append(
            f"<span style='color:#9fb3d9;'>Motore: <b>{cfg.stt.engine}</b> · "
            f"🔊 Campioni audio indicizzati: <b>{total_samples}</b></span>"
        )
        if cfg.stt.engine not in ("samples_hybrid", "samples_only") and total_samples > 0:
            lines.append(
                "<span style='color:#f87171;'><b>⚠️ Hai campioni audio registrati ma il motore "
                f"è ancora '{cfg.stt.engine}'!</b> Vai nella scheda <b>Riconoscimento &amp; Campioni</b> qui sotto "
                "e imposta <b>samples_hybrid</b> per usare i campioni.</span>"
            )
        elif cfg.stt.engine in ("samples_hybrid", "samples_only") and cfg.audio.noise_gate_db <= -75:
            lines.append(
                "<span style='color:#f59e0b;'>💡 Con i campioni audio conviene impostare il "
                "Noise Gate attorno a -45 / -40 dB per riconoscere subito fine parola.</span>"
            )
        self.prefix_summary_label.setText("<br>".join(lines))

    def _sync_ui_from_config(self, refresh_system_tabs: bool = True) -> None:
        cfg = self.controller.config
        self._apply_mode_button_style(
            self.controller.state.mode.value,
            self.controller.state.emoji,
            self.controller.state.label,
        )
        self._tray.refresh_state()
        self.gain_slider.blockSignals(True)
        self.gain_slider.setValue(max(2, min(50, int(round(cfg.audio.input_gain * 10.0)))))
        self.gain_slider.blockSignals(False)
        self.gain_val_label.setText(f"Gain: {cfg.audio.input_gain:.1f}x")

        self.gate_slider.blockSignals(True)
        self.gate_slider.setValue(int(round(cfg.audio.noise_gate_db)))
        self.gate_slider.blockSignals(False)
        self.gate_val_label.setText(f"Gate: {int(round(cfg.audio.noise_gate_db))} dB")
        self._refresh_mics()

        if refresh_system_tabs and hasattr(self, "system_panel"):
            self.system_panel.load_from_config(cfg)

        self._refresh_program_summary()

    def _refresh_mics(self) -> None:
        self.mic_combo.clear()
        self.mic_combo.addItem("(Default di Sistema)", None)
        saved_name = self.controller.config.audio.input_device_name
        saved_idx = self.controller.config.audio.input_device_index
        for dev in list_input_devices():
            self.mic_combo.addItem(dev.display_label, (dev.index, dev.name))
            if saved_name and dev.name.lower() == saved_name.lower():
                self.mic_combo.setCurrentIndex(self.mic_combo.count() - 1)
            elif saved_idx == dev.index and self.mic_combo.currentIndex() == 0:
                self.mic_combo.setCurrentIndex(self.mic_combo.count() - 1)

    def _apply_selected_mic(self) -> None:
        data = self.mic_combo.currentData()
        def _upd(cfg):
            if isinstance(data, tuple) and len(data) == 2:
                cfg.audio.input_device_index = int(data[0])
                cfg.audio.input_device_name = str(data[1])
            else:
                cfg.audio.input_device_index = None
                cfg.audio.input_device_name = ""
        self.controller.config_manager.update(_upd)
        au = self.controller.config.audio
        self.system_panel.sync_audio_controls(
            au.input_gain, au.noise_gate_db, au.input_device_index, au.input_device_name
        )
        self._append_log_ui("info", "Periferica microfonica aggiornata.")

    def _run_mic_test(self) -> None:
        self.mic_test_btn.setEnabled(False)
        self.mic_test_btn.setText("Registrazione 2s...")
        data = self.mic_combo.currentData()
        idx = int(data[0]) if isinstance(data, tuple) else None

        def _worker():
            ok, _peak, msg = AudioCaptureService.run_mic_test_sample(idx, 2.0, True)
            self._bridge.mic_test_done.emit(ok, msg)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_mic_test_done_ui(self, ok: bool, msg: str) -> None:
        self.mic_test_btn.setEnabled(True)
        self.mic_test_btn.setText("🎙️ Testa Microfono (2s)")
        self._append_log_ui("info" if ok else "error", msg)

    def _on_gain_slider_changed(self, value: int) -> None:
        gain = value / 10.0
        self.gain_val_label.setText(f"Gain: {gain:.1f}x")
        self.controller.config_manager.update(
            lambda c: setattr(c.audio, "input_gain", float(gain))
        )
        au = self.controller.config.audio
        self.system_panel.sync_audio_controls(
            au.input_gain, au.noise_gate_db, au.input_device_index, au.input_device_name
        )

    def _on_gate_slider_changed(self, value: int) -> None:
        self.gate_val_label.setText(f"Gate: {value} dB")
        self.controller.config_manager.update(
            lambda c: setattr(c.audio, "noise_gate_db", float(value))
        )
        au = self.controller.config.audio
        self.system_panel.sync_audio_controls(
            au.input_gain, au.noise_gate_db, au.input_device_index, au.input_device_name
        )

    def _send_simulated_command(self) -> None:
        txt = self.cmd_input.text().strip()
        if not txt:
            return
        self.cmd_input.clear()
        self._append_log_ui("info", f"[Test Comando] '{txt}'")
        self.controller.process_text_command(txt, source="ui_sim")

    def _on_add_program_direct(self) -> None:
        wiz = AddProgramWizardDialog(self.controller, parent=self)
        if wiz.exec() and wiz.created_profile is not None:
            prof = wiz.created_profile
            updated = copy.deepcopy(self.controller.config)
            existing_ids = {p.id for p in updated.programs}
            base_id = prof.id
            n = 2
            while prof.id in existing_ids:
                prof.id = f"{base_id}_{n}"
                n += 1
            updated.programs.append(prof)
            self.controller.config_manager.save(updated)
            self._sync_ui_from_config(refresh_system_tabs=False)
            self._append_log_ui(
                "info",
                f"Programma '{prof.name}' aggiunto ({len(prof.functions)} funzioni). "
                "Apri '📱 App / Settings' per gestire tutte le sue funzioni.",
            )

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.controller, parent=self)
        if dlg.exec():
            self.controller.config_manager.save(dlg.edited_config)
            self._sync_ui_from_config(refresh_system_tabs=dlg.loaded_from_file)
            self._append_log_ui("info", "Applicazioni salvate e applicate.")

    def _open_configs_folder(self) -> None:
        folder = get_configs_dir(self.controller.config_manager.path.parent)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_samples_folder(self) -> None:
        folder = self.controller.stt.samples_dir or get_samples_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_load_config(self) -> None:
        configs_dir = get_configs_dir(self.controller.config_manager.path.parent)
        samples_dir = self.controller.stt.samples_dir or get_samples_dir()
        dlg = LoadConfigProfileDialog(
            current_config=self.controller.config,
            configs_dir=configs_dir,
            samples_dir=samples_dir,
            parent=self,
        )
        if not dlg.exec() or dlg.loaded_config is None:
            return
        try:
            backup_path = self.controller.config_manager.path.with_name(
                "config.backup_precedente.json"
            )
            export_config_file(self.controller.config, backup_path, samples_dir=samples_dir)
        except Exception:
            pass
        self.controller.config_manager.save(dlg.loaded_config)
        self._sync_ui_from_config(refresh_system_tabs=True)
        extra = (
            f", {dlg.extracted_samples} campioni estratti"
            if dlg.extracted_samples > 0
            else ""
        )
        self._append_log_ui(
            "info",
            f"Configurazione caricata: '{dlg.loaded_profile_name}' "
            f"({len(dlg.loaded_config.programs)} programmi{extra}).",
        )

    def _on_save_config(self) -> None:
        configs_dir = get_configs_dir(self.controller.config_manager.path.parent)
        samples_dir = self.controller.stt.samples_dir or get_samples_dir()
        dlg = SaveConfigProfileDialog(
            config=self.controller.config,
            configs_dir=configs_dir,
            samples_dir=samples_dir,
            parent=self,
        )
        if not dlg.exec() or dlg.saved_path is None:
            return
        current_ids = {p.id for p in self.controller.config.programs}
        if dlg.selected_program_ids == current_ids or not current_ids:
            self.controller.config_manager.update(
                lambda c: setattr(c.general, "active_profile_name", dlg.profile_name)
            )
            self._sync_ui_from_config(refresh_system_tabs=True)
        self._append_log_ui(
            "info",
            f"Configurazione salvata: '{dlg.saved_path.name}' "
            f"({len(dlg.selected_program_ids)} programmi · {dlg.exported_samples} campioni).",
        )

    def _on_mode_changed_ui(self, mode: str, emoji: str, label: str) -> None:
        self._apply_mode_button_style(mode, emoji, label)
        self._tray.refresh_state()

    def _on_audio_level_ui(self, rms_db: float, peak_db: float, gate_open: bool) -> None:
        gate_db = self.controller.config.audio.noise_gate_db
        self.vu_meter.set_levels(rms_db, peak_db, gate_db, gate_open)
        self.level_label.setText(f"{rms_db:5.1f} dBFS")

    def _on_stt_status_ui(self, engine: str, loaded: bool, message: str) -> None:
        color = "#2ecc71" if loaded else "#f39c12"
        self.stt_status_label.setStyleSheet(f"color: {color};")
        self.stt_status_label.setText(f"STT Offline ({engine}): {message}")
        self._refresh_program_summary()

    def _on_stt_transcript_ui(
        self, text: str, is_final: bool, latency_ms: float, engine: str
    ) -> None:
        if is_final:
            self._append_log_ui(
                "stt", f"[{engine} {latency_ms:.0f}ms] Udito: \"{text}\""
            )

    def _append_log_ui(self, level: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        colors = {
            "error": "#ff6b6b",
            "warning": "#fbbf24",
            "stt": "#60a5fa",
            "info": "#a7f3d0",
        }
        col = colors.get(level, "#d1d5db")
        safe_msg = (
            message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        self.log_view.append(f'<span style="color:#6b7280">[{ts}]</span> <span style="color:{col}">{safe_msg}</span>')

    def restore_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._force_quit and self.controller.config.general.minimize_on_close:
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "Art Director attivo in background",
                f"{self.controller.state.emoji} L'app resta in esecuzione nella System Tray.",
            )
            return
        if hasattr(self, "system_panel"):
            self.system_panel.cleanup()
        self.controller.stop()
        self._tray.hide()
        event.accept()

    def quit_completely(self) -> None:
        if self.controller.config.general.confirm_quit:
            ans = QMessageBox.question(
                self,
                "Esci da Art Director",
                "Chiudere completamente il demone Art Director?",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        self._force_quit = True
        self.close()
