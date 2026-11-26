"""Dynamic 3-Step Program Wizard, Acoustic Sample Recorder, Window Picking HUD, and Program Tab."""

from __future__ import annotations

import copy
import threading
import weakref
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QEventLoop, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config.schema import (
    ActionStep,
    ProgramFunction,
    ProgramProfile,
    compute_function_signature,
    register_or_merge_function,
)
from ..core.app_discovery import InstalledProgram, discover_all_installed_programs
from ..core.controller import ArtDirectorController
from ..core.state import CancellationToken
from ..os_layer.picker import WindowPickerSession
from ..stt.sample_matcher import load_wav_float32, trim_silence
from ..targets.base import MidiOutputHelper


class _VoiceSignalBridge(QObject):
    transcript_received = Signal(str)
    sample_audio_received = Signal(object)
    sample_error_received = Signal(str)
    pick_step_received = Signal(object)
    pick_stop_requested = Signal()


class SampleRecorderWidget(QWidget):
    """Reusable WAV voice-sample recorder, player, and list manager."""

    samples_changed = Signal()

    def __init__(
        self,
        controller: ArtDirectorController,
        label_provider: Callable[[], str],
        initial_samples: list[str] | None = None,
        compact: bool = False,
        expand_list: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._label_provider = label_provider
        self._samples: list[str] = list(initial_samples or [])
        self._recording = False

        self._bridge = _VoiceSignalBridge(self)
        self._bridge.sample_audio_received.connect(self._on_audio_captured)
        self._bridge.sample_error_received.connect(self._on_record_error)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        btn_row = QHBoxLayout()
        self.rec_btn = QPushButton("🔴 Registra Campione Audio")
        self.rec_btn.setStyleSheet(
            "QPushButton { background-color: #991b1b; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #dc2626; }"
        )
        self.rec_btn.clicked.connect(self._toggle_record)

        self.play_btn = QPushButton("▶ Riascolta")
        self.play_btn.clicked.connect(self._play_selected)

        self.del_btn = QPushButton("🗑️")
        self.del_btn.setToolTip("Rimuovi campione selezionato")
        self.del_btn.clicked.connect(self._remove_selected)

        self.status_lbl = QLabel()
        self.status_lbl.setStyleSheet("color: #9fb3d9; font-size: 11px;")

        btn_row.addWidget(self.rec_btn)
        btn_row.addWidget(self.play_btn)
        btn_row.addWidget(self.del_btn)
        if compact:
            btn_row.addWidget(self.status_lbl, stretch=1)
        layout.addLayout(btn_row)

        self.sample_list = QListWidget()
        if expand_list:
            self.sample_list.setMinimumHeight(110)
            layout.addWidget(self.sample_list, stretch=1)
        elif compact:
            self.sample_list.setMinimumHeight(96)
            self.sample_list.setMaximumHeight(130)
            layout.addWidget(self.sample_list)
        else:
            self.sample_list.setMinimumHeight(110)
            self.sample_list.setMaximumHeight(150)
            layout.addWidget(self.sample_list)
        if not compact:
            layout.addWidget(self.status_lbl)

        self._refresh_list()

    @property
    def samples(self) -> list[str]:
        return list(self._samples)

    def set_samples(self, items: list[str]) -> None:
        self._samples = list(items)
        self._refresh_list()

    def _refresh_list(self) -> None:
        self.sample_list.clear()
        for fname in self._samples:
            p = self.controller.stt.sample_library.resolve_path(fname)
            dur_str = ""
            if p.exists():
                try:
                    arr, sr = load_wav_float32(p)
                    dur_str = f" ({arr.size / float(max(1, sr)):.2f}s)"
                except Exception:
                    pass
            item = QListWidgetItem(f"🔊 {Path(fname).name}{dur_str}")
            item.setData(Qt.ItemDataRole.UserRole, fname)
            self.sample_list.addItem(item)
        if not self._recording:
            self.status_lbl.setText(f"Campioni: {len(self._samples)}")

    def _toggle_record(self) -> None:
        if not self._recording:
            self._start_recording()
        else:
            self._stop_recording_manual()

    def _start_recording(self) -> None:
        self._recording = True
        self.controller.set_voice_capture_mode(True)
        self.rec_btn.setText("⏹️ Ferma & Salva")
        self.status_lbl.setText("🎙️ Parla ora nel microfono...")

        if self.controller.audio.is_running:
            self.controller.stt.start_sample_recording(
                lambda arr: self._bridge.sample_audio_received.emit(arr)
            )
            return

        # Fallback: direct short recording if live stream is not running
        def _worker() -> None:
            try:
                import sounddevice as sd

                sr = self.controller.config.audio.sample_rate
                dev = self.controller.config.audio.input_device_index
                rec = sd.rec(
                    int(sr * 2.5), samplerate=sr, channels=1, dtype="float32", device=dev
                )
                sd.wait()
                self._bridge.sample_audio_received.emit(rec.reshape(-1))
            except Exception as exc:
                self._bridge.sample_error_received.emit(str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_recording_manual(self) -> None:
        arr = self.controller.stt.stop_sample_recording()
        self._recording = False
        self.controller.set_voice_capture_mode(False)
        self.rec_btn.setText("🔴 Registra Campione Audio")
        if arr is not None:
            self._save_audio(arr)
        else:
            self.status_lbl.setText("⚠️ Nessun audio rilevato sopra il Gate.")

    def _on_audio_captured(self, audio: object) -> None:
        if not self._recording:
            return
        self._recording = False
        self.controller.set_voice_capture_mode(False)
        self.rec_btn.setText("🔴 Registra Campione Audio")
        if isinstance(audio, np.ndarray):
            self._save_audio(audio)

    def _on_record_error(self, err: str) -> None:
        self._recording = False
        self.controller.set_voice_capture_mode(False)
        self.rec_btn.setText("🔴 Registra Campione Audio")
        self.status_lbl.setText(f"❌ Errore microfono: {err}")

    def _save_audio(self, audio: np.ndarray) -> None:
        sr = self.controller.config.audio.sample_rate
        trimmed = trim_silence(audio, sample_rate=sr)
        if trimmed.size < int(sr * 0.11):
            self.status_lbl.setText("⚠️ Audio troppo breve o troppo basso: avvicinati al microfono.")
            return
        label = self._label_provider().strip() or "comando"
        fname = self.controller.save_recorded_sample(label, trimmed)
        self._samples.append(fname)
        self._refresh_list()
        self.status_lbl.setText(f"✅ Salvato: {fname} ({trimmed.size / float(sr):.2f}s)")
        self.samples_changed.emit()

    def _play_selected(self) -> None:
        row = self.sample_list.currentRow()
        if row < 0 and self._samples:
            row = len(self._samples) - 1
        if 0 <= row < len(self._samples):
            ok, msg = self.controller.play_sample_file(self._samples[row])
            self.status_lbl.setText(msg if ok else f"❌ {msg}")

    def _remove_selected(self) -> None:
        row = self.sample_list.currentRow()
        if row < 0 and self._samples:
            row = len(self._samples) - 1
        if 0 <= row < len(self._samples):
            self._samples.pop(row)
            self._refresh_list()
            self.samples_changed.emit()

    def cleanup(self) -> None:
        if self._recording:
            self._recording = False
            self.controller.stt.stop_sample_recording()
            self.controller.set_voice_capture_mode(False)


def _widget_depth(widget: QWidget | None) -> int:
    depth = 0
    cur = widget.parentWidget() if widget is not None else None
    while cur is not None:
        depth += 1
        cur = cur.parentWidget()
    return depth


class SafeModalDialog(QDialog):
    """Modal QDialog whose exec() loop survives temporary hide()/show() during screen picking."""

    def exec(self) -> int:  # noqa: A003
        self.setResult(0)
        prev_modality = self.windowModality()
        if prev_modality == Qt.WindowModality.NonModal:
            self.setWindowModality(Qt.WindowModality.ApplicationModal)
        loop = QEventLoop(self)
        fin_conn = self.finished.connect(loop.exit)
        dest_conn = self.destroyed.connect(loop.quit)
        try:
            self.show()
            self.raise_()
            self.activateWindow()
            loop.exec()
        finally:
            try:
                self.finished.disconnect(fin_conn)
            except (RuntimeError, TypeError):
                pass
            try:
                self.destroyed.disconnect(dest_conn)
            except (RuntimeError, TypeError):
                pass
            try:
                if prev_modality == Qt.WindowModality.NonModal:
                    self.setWindowModality(prev_modality)
            except RuntimeError:
                pass
        try:
            return self.result()
        except RuntimeError:
            return 0


class PickingHudBar(QWidget):
    """Floating always-on-top draggable HUD pill shown while picking controls in another app."""

    stop_clicked = Signal()

    def __init__(self, app_name: str, os_bridge=None) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._os_bridge = os_bridge
        self._drag_pos = None
        self._cached_screen_rect: tuple[int, int, int, int] = (0, 0, 0, 0)
        self.setWindowTitle(f"Picking su {app_name}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._frame = QFrame(self)
        self._frame.setObjectName("pickingHudFrame")
        self._frame.setStyleSheet(
            "QFrame#pickingHudFrame { background-color: #111827; border: 2px solid #2ecc71; border-radius: 10px; }"
            "QLabel { background: transparent; border: none; color: #f9fafb; }"
            "QPushButton { background-color: #16a34a; color: white; border: none; border-radius: 6px; padding: 6px 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #22c55e; }"
        )
        outer.addWidget(self._frame)

        layout = QHBoxLayout(self._frame)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        self.info_label = QLabel(
            f"🎯 Picking su <b>{app_name}</b>: clicca nella finestra (F9 = Fine · trascina barra per spostare)"
        )
        self.count_label = QLabel("Passi: 0")
        self.count_label.setStyleSheet("color: #60a5fa; font-weight: bold; border: none; background: transparent;")
        self.stop_btn = QPushButton("✅ Fine Picking")
        self.stop_btn.clicked.connect(self._on_stop_clicked)

        layout.addWidget(self.info_label)
        layout.addWidget(self.count_label)
        layout.addWidget(self.stop_btn)
        self.adjustSize()
        self.move(40, 24)

    def _on_stop_clicked(self) -> None:
        from PySide6.QtCore import QTimer

        self.stop_clicked.emit()
        QTimer.singleShot(150, self._close_if_still_open)

    def _close_if_still_open(self) -> None:
        try:
            if self.isVisible():
                self.hide()
                self.close()
        except RuntimeError:
            pass

    def update_count(self, count: int, last_desc: str) -> None:
        self.count_label.setText(f"Passi: {count} ({last_desc})")
        self.adjustSize()
        self._refresh_cached_rect()

    def _refresh_cached_rect(self) -> None:
        """Compute HUD physical screen rect strictly on the Qt GUI thread."""
        pad = 8
        if self._os_bridge is not None:
            try:
                rect = self._os_bridge.get_window_rect(int(self.winId()))
                if rect is not None:
                    rx, ry, rw, rh = rect
                    self._cached_screen_rect = (rx - pad, ry - pad, rw + pad * 2, rh + pad * 2)
                    return
            except Exception:
                pass
        g = self.frameGeometry()
        dpr = max(1.0, float(self.devicePixelRatioF()))
        self._cached_screen_rect = (
            int(round(g.x() * dpr)) - pad,
            int(round(g.y() * dpr)) - pad,
            int(round(g.width() * dpr)) + pad * 2,
            int(round(g.height() * dpr)) + pad * 2,
        )

    def screen_rect_tuple(self) -> tuple[int, int, int, int]:
        """Thread-safe rect getter queried from pynput's background mouse listener."""
        return self._cached_screen_rect

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh_cached_rect()

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self._refresh_cached_rect()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_cached_rect()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_F9, Qt.Key.Key_Escape):
            self.stop_clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class AdvancedStepDialog(SafeModalDialog):
    """Modal to add or edit a direct background protocol step (OSC, Art-Net, MIDI, Open Project, Wait)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        initial_step: ActionStep | None = None,
        default_host: str = "192.168.1.100",
        default_port: int = 10024,
        default_xr18_cmd: str = "",
        default_step_db: float = 3.0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("+ Azione Avanzata / Passo Macro")
        self.resize(540, 440)
        self._step: ActionStep | None = None

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.kind_combo = QComboBox()
        self.kind_combo.addItem(
            "Invio OSC universale (Fisso / +/- Relativo / Toggle — QLC+, XR18, VDJ...)",
            "osc",
        )
        self.kind_combo.addItem(
            "Behringer XR18 / X-Air Smart (alza/abbassa dB, Mute, EQ, FX, Scene)",
            "xr18_cmd",
        )
        self.kind_combo.addItem("Invio Art-Net DMX diretto (es. QLC+)", "artnet")
        self.kind_combo.addItem("Invio MIDI Control Change (CC)", "midi_cc")
        self.kind_combo.addItem("Invio MIDI Note", "midi_note")
        self.kind_combo.addItem(
            "Invio MIDI Program Change (Cambio Patch/Suono)", "midi_pc"
        )
        self.kind_combo.addItem("Apri Progetto/File da Cartella ({nome})", "open_project")
        self.kind_combo.addItem("Cerca / Scrivi Testo (es. Search VirtualDJ)", "paste_text")
        self.kind_combo.addItem("Scorciatoia da Tastiera (Hotkey)", "hotkey")
        self.kind_combo.addItem("Tasto su eventuale Pop-up (es. 'n' per Non salvare)", "hotkey_if_dialog")
        self.kind_combo.addItem("Pausa / Attesa (ms)", "wait")
        self._last_kind = "osc"
        self.kind_combo.currentIndexChanged.connect(self._refresh_fields)
        form.addRow("Tipo azione:", self.kind_combo)

        self.host_edit = QLineEdit(default_host or "192.168.1.100")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(int(default_port or 10024))
        self.osc_addr_edit = QLineEdit("/ch/01/mix/fader")
        self.osc_mode_combo = QComboBox()
        self.osc_mode_combo.addItem("Imposta valore fisso", "set")
        self.osc_mode_combo.addItem("Varia di +/- (relativo tra Min e Max)", "relative")
        self.osc_mode_combo.addItem("Alterna ON / OFF (Toggle Min <-> Max)", "toggle")
        self.osc_mode_combo.currentIndexChanged.connect(self._refresh_fields)
        self.osc_val_spin = QDoubleSpinBox()
        self.osc_val_spin.setDecimals(3)
        self.osc_val_spin.setSingleStep(0.05)
        self.osc_val_spin.setRange(-10000.0, 10000.0)
        self.osc_val_spin.setValue(0.75)
        self.osc_type_combo = QComboBox()
        self.osc_type_combo.addItems(["float", "int"])

        range_row = QHBoxLayout()
        self.osc_min_spin = QDoubleSpinBox()
        self.osc_min_spin.setDecimals(3)
        self.osc_min_spin.setRange(-10000.0, 10000.0)
        self.osc_min_spin.setValue(0.0)
        self.osc_max_spin = QDoubleSpinBox()
        self.osc_max_spin.setDecimals(3)
        self.osc_max_spin.setRange(-10000.0, 10000.0)
        self.osc_max_spin.setValue(1.0)
        range_row.addWidget(QLabel("Min:"))
        range_row.addWidget(self.osc_min_spin)
        range_row.addWidget(QLabel("Max:"))
        range_row.addWidget(self.osc_max_spin)

        self.osc_query_chk = QCheckBox(
            "Leggi stato reale dal mixer prima di variare (UDP query, consigliato su XR18)"
        )
        self.osc_query_chk.setChecked(True)

        self.xr18_cmd_edit = QLineEdit(default_xr18_cmd)
        self.xr18_cmd_edit.setPlaceholderText(
            "es: alza canale 7 · canale 1 phantom on · inverti fase canale 3 · apri tab input"
        )
        self.xr18_step_spin = QDoubleSpinBox()
        self.xr18_step_spin.setDecimals(1)
        self.xr18_step_spin.setSingleStep(0.5)
        self.xr18_step_spin.setRange(0.5, 12.0)
        self.xr18_step_spin.setSuffix(" dB")
        self.xr18_step_spin.setValue(max(0.5, float(default_step_db or 3.0)))
        self.xr18_help_lbl = QLabel(
            "Esempi: 'alza canale 7', 'canale 1 phantom on', 'inverti fase canale 3', "
            "'canale 1 trim -3 db', 'collega canali 1 2', 'apri tab input', 'apri input canale 3'."
        )
        self.xr18_help_lbl.setWordWrap(True)
        self.xr18_help_lbl.setStyleSheet("color: #9fb3d9; font-size: 11px;")

        self.art_uni_spin = QSpinBox()
        self.art_uni_spin.setRange(0, 32767)
        self.art_ch_spin = QSpinBox()
        self.art_ch_spin.setRange(1, 512)
        self.art_val_spin = QSpinBox()
        self.art_val_spin.setRange(0, 255)
        self.art_val_spin.setValue(255)
        self.art_bo_chk = QCheckBox("Blackout generale (azzera tutti i 512 canali)")

        self.midi_port_combo = QComboBox()
        self.midi_port_combo.setEditable(True)
        self.midi_port_combo.addItems(MidiOutputHelper.list_output_ports())
        self.midi_ch_spin = QSpinBox()
        self.midi_ch_spin.setRange(1, 16)
        self.midi_ctrl_spin = QSpinBox()
        self.midi_ctrl_spin.setRange(0, 127)
        self.midi_val_spin = QSpinBox()
        self.midi_val_spin.setRange(0, 127)
        self.midi_val_spin.setValue(127)
        self.midi_bank_msb_spin = QSpinBox()
        self.midi_bank_msb_spin.setRange(-1, 127)
        self.midi_bank_msb_spin.setValue(-1)
        self.midi_bank_msb_spin.setSpecialValueText("Nessuno (off)")
        self.midi_bank_msb_spin.setToolTip(
            "Opzionale: invia Bank Select MSB (CC#0) prima del Program Change (-1 = non inviare)"
        )
        self.midi_bank_lsb_spin = QSpinBox()
        self.midi_bank_lsb_spin.setRange(-1, 127)
        self.midi_bank_lsb_spin.setValue(-1)
        self.midi_bank_lsb_spin.setSpecialValueText("Nessuno (off)")
        self.midi_bank_lsb_spin.setToolTip(
            "Opzionale: invia Bank Select LSB (CC#32) prima del Program Change (-1 = non inviare)"
        )

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        folder_btn = QPushButton("Sfoglia...")
        folder_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.folder_edit)
        folder_row.addWidget(folder_btn)
        self.ext_edit = QLineEdit(".cwp, .cwb, .wrk, .rpp")
        self.use_param_chk = QCheckBox("Usa nome parlato dinamico {nome} (richiede fallback Vosk/Whisper)")
        self.use_param_chk.setChecked(True)
        self.use_param_chk.toggled.connect(self._refresh_fields)

        fixed_row = QHBoxLayout()
        self.fixed_file_edit = QLineEdit()
        self.fixed_file_edit.setPlaceholderText("Opzionale se togli la spunta sopra (funziona coi soli campioni)")
        fixed_btn = QPushButton("Sfoglia file...")
        fixed_btn.clicked.connect(self._browse_fixed_file)
        fixed_row.addWidget(self.fixed_file_edit)
        fixed_row.addWidget(fixed_btn)

        self.open_hotkey_edit = QLineEdit()
        self.open_hotkey_edit.setPlaceholderText(
            "Opzionale: es. o oppure <ctrl>+o (se il programma è già aperto)"
        )

        self.paste_before_edit = QLineEdit()
        self.paste_before_edit.setPlaceholderText(
            "Opzionale: tasto per andare su Cerca (es. F3 o tasto VDJ 'search')"
        )
        paste_row = QHBoxLayout()
        self.paste_text_edit = QLineEdit()
        self.paste_text_edit.setPlaceholderText(
            "Nome brano / testo da incollare (vuoto = svuota barra Cerca)"
        )
        paste_browse_btn = QPushButton("Sfoglia brano...")
        paste_browse_btn.clicked.connect(self._browse_paste_song_name)
        paste_row.addWidget(self.paste_text_edit)
        paste_row.addWidget(paste_browse_btn)
        self.paste_clear_chk = QCheckBox(
            "Cancella testo precedente prima (<ctrl>+a)"
        )
        self.paste_clear_chk.setChecked(True)
        self.paste_after_edit = QLineEdit()
        self.paste_after_edit.setPlaceholderText(
            "Opzionale: tasto finale (es. enter, down, o lascia vuoto per aggiungere step)"
        )

        self.hotkey_edit = QLineEdit("<ctrl>+w")
        self.wait_spin = QSpinBox()
        self.wait_spin.setRange(50, 15000)
        self.wait_spin.setValue(500)

        self._rows: list[tuple[set[str], QWidget, QWidget | None, Callable[[], bool] | None]] = []

        def _add(
            kinds: set[str],
            label: str,
            widget_or_layout,
            extra_cond: Callable[[], bool] | None = None,
        ) -> QLabel:
            lbl = QLabel(label)
            if isinstance(widget_or_layout, QHBoxLayout):
                wrap = QWidget()
                wrap.setLayout(widget_or_layout)
                form.addRow(lbl, wrap)
                self._rows.append((kinds, wrap, lbl, extra_cond))
            else:
                form.addRow(lbl, widget_or_layout)
                self._rows.append((kinds, widget_or_layout, lbl, extra_cond))
            return lbl

        _is_osc_var = lambda: self.osc_mode_combo.currentData() in ("relative", "toggle")
        _is_osc_val = lambda: self.osc_mode_combo.currentData() in ("set", "relative")

        _add({"osc", "xr18_cmd", "artnet"}, "Host IP:", self.host_edit)
        _add({"osc", "xr18_cmd", "artnet"}, "Porta UDP:", self.port_spin)
        _add({"osc"}, "Indirizzo OSC:", self.osc_addr_edit)
        _add({"osc"}, "Modalità OSC:", self.osc_mode_combo)
        _add({"osc"}, "Valore / Step (+/-):", self.osc_val_spin, _is_osc_val)
        _add({"osc"}, "Intervallo:", range_row, _is_osc_var)
        _add({"osc"}, "Tipo OSC:", self.osc_type_combo)
        _add({"osc"}, "", self.osc_query_chk, _is_osc_var)
        _add({"xr18_cmd"}, "Comando XR18:", self.xr18_cmd_edit)
        _add({"xr18_cmd"}, "Step +/- default:", self.xr18_step_spin)
        _add({"xr18_cmd"}, "", self.xr18_help_lbl)
        _add({"artnet"}, "Universo Art-Net:", self.art_uni_spin)
        _add({"artnet"}, "Canale DMX (1-512):", self.art_ch_spin)
        _add({"artnet"}, "Valore DMX (0-255):", self.art_val_spin)
        _add({"artnet"}, "", self.art_bo_chk)
        _add({"midi_cc", "midi_note", "midi_pc"}, "Porta MIDI Out:", self.midi_port_combo)
        _add({"midi_cc", "midi_note", "midi_pc"}, "Canale MIDI (1-16):", self.midi_ch_spin)
        _add({"midi_cc", "midi_note"}, "Numero CC / Nota:", self.midi_ctrl_spin)
        self._midi_val_lbl = _add(
            {"midi_cc", "midi_note", "midi_pc"}, "Valore (0-127):", self.midi_val_spin
        )
        _add({"midi_pc"}, "Bank MSB (CC#0, opzionale):", self.midi_bank_msb_spin)
        _add({"midi_pc"}, "Bank LSB (CC#32, opzionale):", self.midi_bank_lsb_spin)
        _add({"open_project"}, "Cartella progetti:", folder_row)
        _add({"open_project"}, "Estensioni file:", self.ext_edit)
        _add({"open_project"}, "", self.use_param_chk)
        _add({"open_project"}, "File progetto fisso:", fixed_row)
        _add({"open_project"}, "Scorciatoia Apri se già aperto:", self.open_hotkey_edit)
        _add({"paste_text"}, "Scorciatoia prima (es. search VDJ):", self.paste_before_edit)
        _add({"paste_text"}, "Testo / Brano da cercare:", paste_row)
        _add({"paste_text"}, "", self.paste_clear_chk)
        _add({"paste_text"}, "Tasto dopo incolla (opzionale):", self.paste_after_edit)
        _add(
            {"hotkey", "hotkey_if_dialog"},
            "Tasti (es. space, enter, c, <ctrl>+w):",
            self.hotkey_edit,
        )
        _add({"wait", "hotkey_if_dialog"}, "Attesa / Timeout Pop-up (ms):", self.wait_spin)

        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if initial_step is not None:
            self._load_initial_step(initial_step)
        self._refresh_fields()

    def _load_initial_step(self, st: ActionStep) -> None:
        idx = self.kind_combo.findData(st.kind)
        if idx >= 0:
            self._last_kind = st.kind
            self.kind_combo.setCurrentIndex(idx)
        if st.kind == "osc":
            self.host_edit.setText(st.osc_host)
            self.port_spin.setValue(int(st.osc_port))
            self.osc_addr_edit.setText(st.osc_address)
            m_idx = self.osc_mode_combo.findData(st.osc_mode)
            if m_idx >= 0:
                self.osc_mode_combo.setCurrentIndex(m_idx)
            self.osc_val_spin.setValue(float(st.osc_value))
            self.osc_min_spin.setValue(float(st.osc_min))
            self.osc_max_spin.setValue(float(st.osc_max))
            self.osc_query_chk.setChecked(bool(st.osc_query_before_update))
            self.osc_type_combo.setCurrentText(st.osc_type)
        elif st.kind == "xr18_cmd":
            self.host_edit.setText(st.osc_host)
            self.port_spin.setValue(int(st.osc_port))
            self.xr18_cmd_edit.setText(st.xr18_command)
            self.xr18_step_spin.setValue(max(0.5, float(st.xr18_step_db or 3.0)))
        elif st.kind == "artnet":
            self.host_edit.setText(st.artnet_host)
            self.port_spin.setValue(int(st.artnet_port))
            self.art_uni_spin.setValue(int(st.artnet_universe))
            self.art_ch_spin.setValue(int(st.artnet_channel))
            self.art_val_spin.setValue(int(st.artnet_value))
            self.art_bo_chk.setChecked(bool(st.artnet_blackout))
        elif st.kind in ("midi_cc", "midi_note", "midi_pc"):
            self.midi_port_combo.setCurrentText(st.midi_port)
            self.midi_ch_spin.setValue(int(st.midi_channel))
            self.midi_ctrl_spin.setValue(int(st.midi_control))
            self.midi_val_spin.setValue(int(st.midi_value))
            self.midi_bank_msb_spin.setValue(int(getattr(st, "midi_bank_msb", -1)))
            self.midi_bank_lsb_spin.setValue(int(getattr(st, "midi_bank_lsb", -1)))
        elif st.kind == "open_project":
            self.folder_edit.setText(st.project_folders[0] if st.project_folders else "")
            self.ext_edit.setText(", ".join(st.project_extensions))
            self.use_param_chk.setChecked(bool(st.use_spoken_param))
            self.fixed_file_edit.setText(st.fixed_file_path)
            self.open_hotkey_edit.setText(st.open_hotkey)
        elif st.kind == "paste_text":
            self.paste_before_edit.setText(st.paste_before_hotkey)
            self.paste_text_edit.setText(st.paste_text)
            self.paste_clear_chk.setChecked(bool(st.paste_clear_first))
            self.paste_after_edit.setText(st.paste_after_hotkey)
        elif st.kind in ("hotkey", "hotkey_if_dialog"):
            self.hotkey_edit.setText(st.hotkey)
            self.wait_spin.setValue(int(st.delay_ms))
        elif st.kind == "wait":
            self.wait_spin.setValue(int(st.delay_ms))

    @property
    def step(self) -> ActionStep | None:
        return self._step

    def _browse_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Seleziona cartella progetti")
        if d:
            self.folder_edit.setText(d)

    def _browse_fixed_file(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Seleziona file progetto fisso")
        if p:
            self.fixed_file_edit.setText(p)
            self.use_param_chk.setChecked(False)

    def _browse_paste_song_name(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Seleziona brano/file per ricavarne il nome")
        if p:
            self.paste_text_edit.setText(Path(p).stem)

    def _refresh_fields(self) -> None:
        kind = self.kind_combo.currentData()
        if kind in ("osc", "xr18_cmd") and self._last_kind == "artnet":
            if self.host_edit.text() == "127.0.0.1":
                self.host_edit.setText("192.168.1.100")
            if self.port_spin.value() == 6454:
                self.port_spin.setValue(10024)
        elif kind == "artnet" and self._last_kind != "artnet":
            self.host_edit.setText("127.0.0.1")
            self.port_spin.setValue(6454)
        elif kind == "hotkey_if_dialog" and self._last_kind != "hotkey_if_dialog":
            if self.hotkey_edit.text().strip() in ("", "<ctrl>+w"):
                self.hotkey_edit.setText("n")
            if self.wait_spin.value() == 500:
                self.wait_spin.setValue(800)
        elif kind == "hotkey" and self._last_kind == "hotkey_if_dialog":
            if self.hotkey_edit.text().strip() == "n":
                self.hotkey_edit.setText("<ctrl>+w")
        self._last_kind = str(kind)
        if hasattr(self, "_midi_val_lbl") and self._midi_val_lbl is not None:
            self._midi_val_lbl.setText(
                "Programma / Patch (0-127):"
                if kind == "midi_pc"
                else "Valore (0-127):"
            )
        for kinds, widget, lbl, extra_cond in self._rows:
            vis = (kind in kinds) and (extra_cond() if extra_cond is not None else True)
            widget.setVisible(vis)
            if lbl:
                lbl.setVisible(vis)
        self.fixed_file_edit.setEnabled(not self.use_param_chk.isChecked())

    def _on_ok(self) -> None:
        kind = str(self.kind_combo.currentData())
        if kind == "osc":
            self._step = ActionStep(
                kind="osc",
                osc_host=self.host_edit.text().strip() or "127.0.0.1",
                osc_port=self.port_spin.value(),
                osc_address=self.osc_addr_edit.text().strip(),
                osc_value=float(self.osc_val_spin.value()),
                osc_type=self.osc_type_combo.currentText(),
                osc_mode=str(self.osc_mode_combo.currentData() or "set"),
                osc_min=float(self.osc_min_spin.value()),
                osc_max=float(self.osc_max_spin.value()),
                osc_query_before_update=self.osc_query_chk.isChecked(),
            )
        elif kind == "xr18_cmd":
            self._step = ActionStep(
                kind="xr18_cmd",
                osc_host=self.host_edit.text().strip() or "192.168.1.100",
                osc_port=self.port_spin.value(),
                xr18_command=self.xr18_cmd_edit.text().strip(),
                xr18_step_db=float(self.xr18_step_spin.value()),
            )
        elif kind == "artnet":
            self._step = ActionStep(
                kind="artnet",
                artnet_host=self.host_edit.text().strip() or "127.0.0.1",
                artnet_port=self.port_spin.value(),
                artnet_universe=self.art_uni_spin.value(),
                artnet_channel=self.art_ch_spin.value(),
                artnet_value=self.art_val_spin.value(),
                artnet_blackout=self.art_bo_chk.isChecked(),
            )
        elif kind in ("midi_cc", "midi_note", "midi_pc"):
            self._step = ActionStep(
                kind=kind,
                midi_port=self.midi_port_combo.currentText().strip(),
                midi_channel=self.midi_ch_spin.value(),
                midi_control=0 if kind == "midi_pc" else self.midi_ctrl_spin.value(),
                midi_value=self.midi_val_spin.value(),
                midi_bank_msb=self.midi_bank_msb_spin.value() if kind == "midi_pc" else -1,
                midi_bank_lsb=self.midi_bank_lsb_spin.value() if kind == "midi_pc" else -1,
            )
        elif kind == "open_project":
            folders = [self.folder_edit.text().strip()] if self.folder_edit.text().strip() else []
            exts = [e.strip() for e in self.ext_edit.text().split(",") if e.strip()]
            self._step = ActionStep(
                kind="open_project",
                project_folders=folders,
                project_extensions=exts,
                use_spoken_param=self.use_param_chk.isChecked(),
                fixed_file_path=self.fixed_file_edit.text().strip(),
                open_hotkey=self.open_hotkey_edit.text().strip(),
            )
        elif kind == "paste_text":
            self._step = ActionStep(
                kind="paste_text",
                paste_text=self.paste_text_edit.text(),
                paste_clear_first=self.paste_clear_chk.isChecked(),
                paste_before_hotkey=self.paste_before_edit.text().strip(),
                paste_after_hotkey=self.paste_after_edit.text().strip(),
            )
        elif kind == "hotkey":
            self._step = ActionStep(kind="hotkey", hotkey=self.hotkey_edit.text().strip())
        elif kind == "hotkey_if_dialog":
            self._step = ActionStep(
                kind="hotkey_if_dialog",
                hotkey=self.hotkey_edit.text().strip() or "n",
                delay_ms=self.wait_spin.value(),
            )
        else:
            self._step = ActionStep(kind="wait", delay_ms=self.wait_spin.value())
        self.accept()


class FunctionRecorderDialog(SafeModalDialog):
    """Step 3 Dialog: Record Audio Sample(s) + Pick Single/Macro Actions + CONFERMA."""

    def __init__(
        self,
        controller: ArtDirectorController,
        program: ProgramProfile,
        parent: QWidget | None = None,
        start_with_advanced: bool = False,
        existing_function: ProgramFunction | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.program = program
        self._existing_aliases: list[str] = (
            list(existing_function.aliases) if existing_function is not None else []
        )
        title_verb = "Modifica" if existing_function is not None else "Nuova"
        self.setWindowTitle(f"{title_verb} Funzione / Macro — {program.name}")
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(
                min(1020, int(avail.width() * 0.92)),
                max(500, min(680, int(avail.height() * 0.84))),
            )
        else:
            self.resize(980, 620)

        self._steps: list[ActionStep] = []
        self._picker: WindowPickerSession | None = None
        self._hud: PickingHudBar | None = None
        self._hud_destroy_cb = None
        self._hidden_windows: list[QWidget] = []
        self._stopping_pick = False

        self._bridge = _VoiceSignalBridge(self)
        self._bridge.pick_step_received.connect(self._on_pick_step_captured)
        self._bridge.pick_stop_requested.connect(
            self._stop_picking, Qt.ConnectionType.QueuedConnection
        )
        self.finished.connect(self._on_dialog_finished)

        outer_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        outer_layout.addWidget(splitter, stretch=1)

        # ---- Step 3A (Left Column): Label + Audio Sample Recording (🔴)
        cmd_box = QGroupBox("1. Nome Comando & Campioni Audio (Shure / Sennheiser)")
        cmd_layout = QVBoxLayout(cmd_box)
        self.cmd_edit = QLineEdit()
        self.cmd_edit.setPlaceholderText(
            "Nome funzione (es: 'Muta voce') oppure frase con {nome} per fallback STT"
        )
        self._no_prefix_manual = False
        self.cmd_edit.textChanged.connect(self._on_cmd_text_changed)
        cmd_layout.addWidget(self.cmd_edit)

        self.sample_recorder = SampleRecorderWidget(
            controller=self.controller,
            label_provider=lambda: f"{self.program.name}_{self.cmd_edit.text().strip() or 'funzione'}",
            compact=False,
            expand_list=True,
            parent=self,
        )
        cmd_layout.addWidget(self.sample_recorder, stretch=1)
        hint_lbl = QLabel(
            "Suggerimento: puoi registrare 2-3 campioni dello stesso comando (alias acustici). "
            "Se ripicki lo stesso controllo in seguito, verrà aggiunto come alias automatico."
        )
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet("color: #9fb3d9; font-size: 11px;")
        cmd_layout.addWidget(hint_lbl)
        splitter.addWidget(cmd_box)

        # ---- Step 3B (Right Column): Window Picking / Macro Sequence / Advanced Step
        act_box = QGroupBox("2. Picking nella finestra aperta o Sequenza Macro")
        act_layout = QVBoxLayout(act_box)

        pick_btns = QHBoxLayout()
        self.pick_btn = QPushButton(f"🎯 Picking nella finestra ({program.name})")
        self.pick_btn.setStyleSheet(
            "QPushButton { background-color: #1d4ed8; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #2563eb; }"
        )
        self.pick_btn.clicked.connect(self._start_picking)

        self.adv_btn = QPushButton("+ Azione Avanzata (OSC / Art-Net / MIDI / Progetto)")
        self.adv_btn.clicked.connect(self._add_advanced_step)

        pick_btns.addWidget(self.pick_btn)
        pick_btns.addWidget(self.adv_btn)
        act_layout.addLayout(pick_btns)

        self.steps_list = QListWidget()
        self.steps_list.setMinimumHeight(180)
        self.steps_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.steps_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.steps_list.customContextMenuRequested.connect(self._on_steps_context_menu)
        self.steps_list.itemDoubleClicked.connect(self._edit_selected_step)
        self._del_step_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Delete),
            self.steps_list,
            activated=self._remove_selected_step,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )
        act_layout.addWidget(self.steps_list, stretch=1)

        edit_row = QHBoxLayout()
        edit_step_btn = QPushButton("✏️ Modifica Passo")
        edit_step_btn.clicked.connect(self._edit_selected_step)
        rem_step_btn = QPushButton("🗑️ Rimuovi Passo (Canc)")
        rem_step_btn.clicked.connect(self._remove_selected_step)
        clear_btn = QPushButton("Svuota Passi")
        clear_btn.clicked.connect(self._clear_steps)
        edit_row.addWidget(edit_step_btn)
        edit_row.addWidget(rem_step_btn)
        edit_row.addWidget(clear_btn)
        edit_row.addStretch(1)
        act_layout.addLayout(edit_row)

        self.focus_chk = QCheckBox("Porta finestra in primo piano prima di eseguire click/tasti")
        self.focus_chk.setChecked(True)
        self.launch_chk = QCheckBox("Avvia il programma automaticamente se è chiuso")
        self.launch_chk.setChecked(True)
        self.no_prefix_chk = QCheckBox(
            "Consenti comando vocale anche senza prefisso programma (consigliato con {nome})"
        )
        self.no_prefix_chk.toggled.connect(self._on_no_prefix_toggled)
        act_layout.addWidget(self.focus_chk)
        act_layout.addWidget(self.launch_chk)
        act_layout.addWidget(self.no_prefix_chk)
        splitter.addWidget(act_box)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([420, 540])

        # ---- Final CONFERMA button
        bottom = QHBoxLayout()
        cancel_btn = QPushButton("Annulla")
        cancel_btn.clicked.connect(self.reject)
        self.confirm_btn = QPushButton("CONFERMA")
        self.confirm_btn.setMinimumHeight(40)
        self.confirm_btn.setStyleSheet(
            "QPushButton { background-color: #15803d; color: white; font-size: 14px; font-weight: 800; }"
            "QPushButton:hover { background-color: #16a34a; }"
        )
        self.confirm_btn.clicked.connect(self._on_confirm)
        bottom.addStretch(1)
        bottom.addWidget(cancel_btn)
        bottom.addWidget(self.confirm_btn)
        outer_layout.addLayout(bottom)

        if existing_function is not None:
            self.cmd_edit.setText(existing_function.primary_command)
            self.sample_recorder.set_samples(existing_function.sample_files)
            self._steps = copy.deepcopy(existing_function.steps)
            self.focus_chk.setChecked(existing_function.focus_before_run)
            self.launch_chk.setChecked(existing_function.launch_if_closed)
            self.no_prefix_chk.setChecked(existing_function.allow_without_prefix)
            self._no_prefix_manual = True
            self._refresh_steps_list()
        elif start_with_advanced:
            self._add_advanced_step()

    @property
    def allow_without_prefix(self) -> bool:
        return self.no_prefix_chk.isChecked()

    def _on_no_prefix_toggled(self, _checked: bool) -> None:
        if self.no_prefix_chk.hasFocus():
            self._no_prefix_manual = True

    def _on_cmd_text_changed(self, text: str) -> None:
        if not self._no_prefix_manual and ("{" in text and "}" in text):
            self.no_prefix_chk.setChecked(True)

    @property
    def result_data(self) -> tuple[list[str], list[ActionStep], bool, bool, list[str]] | None:
        cmd = self.cmd_edit.text().strip()
        samples = self.sample_recorder.samples
        if (not cmd and not samples) or not self._steps:
            return None
        if not cmd:
            cmd = Path(samples[0]).stem
        return (
            [cmd],
            list(self._steps),
            self.focus_chk.isChecked(),
            self.launch_chk.isChecked(),
            samples,
        )

    def _build_pick_patterns(self) -> list[str]:
        patterns: list[str] = []
        for candidate in (
            *self.program.window_title_patterns,
            self.program.name,
            Path(self.program.executable).stem if self.program.executable.strip() else "",
        ):
            clean = candidate.strip()
            if clean and clean not in patterns:
                patterns.append(clean)
        return patterns

    def _start_picking(self) -> None:
        self._cleanup_picking_session(restore_dialogs=False)

        # Hide ALL visible QDialogs (Wizard, Settings, self) so Qt's activeModalWidget becomes None
        # cleanly and PickingHudBar stays completely clickable without toggling modality flags.
        # SafeModalDialog.exec() only exits on finished/destroyed, never on hide().
        hidden: list[QWidget] = [
            w for w in QApplication.topLevelWidgets()
            if w is not self and isinstance(w, QDialog) and w.isVisible()
        ]
        hidden.sort(key=_widget_depth, reverse=True)
        for w in hidden:
            w.hide()
        self._hidden_windows = hidden
        self.hide()

        patterns = self._build_pick_patterns()
        hud = PickingHudBar(self.program.name, os_bridge=self.controller.os_bridge)
        self._hud = hud
        hud.stop_clicked.connect(self._stop_picking, Qt.ConnectionType.QueuedConnection)
        hud_ref = weakref.ref(hud)

        def _close_orphaned_hud(_obj=None, ref=hud_ref) -> None:
            target = ref()
            if target is not None:
                try:
                    target.hide()
                    target.close()
                except RuntimeError:
                    pass

        self._hud_destroy_cb = _close_orphaned_hud
        self.destroyed.connect(_close_orphaned_hud)
        hud.show()
        hud.raise_()
        QApplication.processEvents()

        self.controller.program_executor.open_or_focus_program(
            self.program, CancellationToken()
        )

        self._picker = WindowPickerSession(
            os_bridge=self.controller.os_bridge,
            window_patterns=patterns,
            ignore_rects_provider=lambda h=hud_ref: (
                [h().screen_rect_tuple()] if h() is not None else []
            ),
            on_step=lambda st: self._bridge.pick_step_received.emit(st),
            on_stop_requested=lambda: self._bridge.pick_stop_requested.emit(),
            process_name=self.program.process_name,
            executable=self.program.executable,
        )
        ok, msg = self._picker.start()
        if not ok:
            self._stop_picking()
            QMessageBox.warning(self, "Errore Picking", msg)
            return

    def _on_pick_step_captured(self, step: ActionStep) -> None:
        if self._hud and self._picker:
            cur = self._picker.steps
            self._hud.update_count(len(cur), step.describe())

    def _cleanup_picking_session(self, restore_dialogs: bool = True) -> list[ActionStep]:
        if self._hud_destroy_cb is not None:
            try:
                self.destroyed.disconnect(self._hud_destroy_cb)
            except (RuntimeError, TypeError):
                pass
            self._hud_destroy_cb = None
        if self._hud is not None:
            hud = self._hud
            self._hud = None
            try:
                hud.hide()
                hud.close()
            except RuntimeError:
                pass
        captured: list[ActionStep] = []
        if self._picker is not None:
            try:
                captured = self._picker.stop()
            finally:
                self._picker = None
        if restore_dialogs and self._hidden_windows:
            for w in reversed(self._hidden_windows):
                w.show()
                w.raise_()
            self._hidden_windows.clear()
        return captured

    def _stop_picking(self) -> None:
        if self._stopping_pick:
            return
        self._stopping_pick = True
        try:
            captured = self._cleanup_picking_session(restore_dialogs=True)
            if captured:
                self._steps.extend(captured)
                self._refresh_steps_list()
            self.showNormal()
            self.raise_()
            self.activateWindow()
        finally:
            self._stopping_pick = False

    def _on_dialog_finished(self, _res: int = 0) -> None:
        self._cleanup_picking_session(restore_dialogs=True)

    def _default_osc_host_port(self) -> tuple[str, int]:
        for step in reversed(self._steps):
            if step.kind in ("osc", "xr18_cmd") and step.osc_host.strip():
                return step.osc_host.strip(), int(step.osc_port or 10024)
        for fn in reversed(self.program.functions):
            for step in reversed(fn.steps):
                if step.kind in ("osc", "xr18_cmd") and step.osc_host.strip():
                    return step.osc_host.strip(), int(step.osc_port or 10024)
        xr_cfg = self.controller.config.xr18
        return xr_cfg.host or "192.168.1.100", int(xr_cfg.port or 10024)

    def _add_advanced_step(self) -> None:
        xr_cfg = self.controller.config.xr18
        def_host, def_port = self._default_osc_host_port()
        dlg = AdvancedStepDialog(
            parent=self,
            default_host=def_host,
            default_port=def_port,
            default_xr18_cmd=self.cmd_edit.text().strip(),
            default_step_db=float(xr_cfg.step_db or 3.0),
        )
        if dlg.exec() and dlg.step is not None:
            self._steps.append(dlg.step)
            self._refresh_steps_list()

    def _edit_selected_step(self, _item=None) -> None:
        row = self.steps_list.currentRow()
        if not (0 <= row < len(self._steps)):
            return
        cur = self._steps[row]
        if cur.kind not in (
            "osc",
            "xr18_cmd",
            "artnet",
            "midi_cc",
            "midi_note",
            "open_project",
            "paste_text",
            "hotkey",
            "hotkey_if_dialog",
            "wait",
        ):
            return
        dlg = AdvancedStepDialog(parent=self, initial_step=cur)
        if dlg.exec() and dlg.step is not None:
            self._steps[row] = dlg.step
            self._refresh_steps_list()

    def _remove_selected_step(self) -> None:
        rows = sorted(
            {idx.row() for idx in self.steps_list.selectedIndexes()}, reverse=True
        )
        if not rows:
            cur = self.steps_list.currentRow()
            if 0 <= cur < len(self._steps):
                rows = [cur]
        if not rows:
            return
        last_removed = rows[-1]
        for r in rows:
            if 0 <= r < len(self._steps):
                self._steps.pop(r)
        self._refresh_steps_list()
        if self._steps:
            self.steps_list.setCurrentRow(min(last_removed, len(self._steps) - 1))

    def _duplicate_selected_step(self) -> None:
        row = self.steps_list.currentRow()
        if 0 <= row < len(self._steps):
            self._steps.insert(row + 1, copy.deepcopy(self._steps[row]))
            self._refresh_steps_list()
            self.steps_list.setCurrentRow(row + 1)

    def _move_selected_step(self, delta: int) -> None:
        row = self.steps_list.currentRow()
        new_row = row + delta
        if 0 <= row < len(self._steps) and 0 <= new_row < len(self._steps):
            self._steps[row], self._steps[new_row] = self._steps[new_row], self._steps[row]
            self._refresh_steps_list()
            self.steps_list.setCurrentRow(new_row)

    def _on_steps_context_menu(self, pos) -> None:
        item = self.steps_list.itemAt(pos)
        if item is not None:
            if not item.isSelected():
                self.steps_list.setCurrentItem(item)
        row = self.steps_list.currentRow()
        if not (0 <= row < len(self._steps)):
            return
        menu = QMenu(self)
        act_edit = menu.addAction("✏️ Modifica passo")
        act_dup = menu.addAction("📑 Duplica passo")
        act_up = menu.addAction("⬆️ Sposta su")
        act_down = menu.addAction("⬇️ Sposta giù")
        menu.addSeparator()
        act_del = menu.addAction("🗑️ Elimina passo (Canc)")
        act_up.setEnabled(row > 0)
        act_down.setEnabled(row < len(self._steps) - 1)
        chosen = menu.exec(self.steps_list.viewport().mapToGlobal(pos))
        if chosen == act_edit:
            self._edit_selected_step()
        elif chosen == act_dup:
            self._duplicate_selected_step()
        elif chosen == act_up:
            self._move_selected_step(-1)
        elif chosen == act_down:
            self._move_selected_step(1)
        elif chosen == act_del:
            self._remove_selected_step()

    def _clear_steps(self) -> None:
        self._steps.clear()
        self._refresh_steps_list()

    def _refresh_steps_list(self) -> None:
        self.steps_list.clear()
        for idx, st in enumerate(self._steps, start=1):
            self.steps_list.addItem(f"{idx}. {st.describe()}")

    def _on_confirm(self) -> None:
        if not self.cmd_edit.text().strip() and not self.sample_recorder.samples:
            QMessageBox.warning(
                self,
                "Comando mancante",
                "Registra almeno un campione audio oppure scrivi il comando vocale.",
            )
            return
        if not self._steps:
            QMessageBox.warning(
                self,
                "Nessuna azione",
                "Fai Picking nella finestra del programma o aggiungi un'Azione Avanzata.",
            )
            return
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.sample_recorder.cleanup()
        self._cleanup_picking_session(restore_dialogs=True)
        super().closeEvent(event)


class AddProgramWizardDialog(SafeModalDialog):
    """3-Step Wizard implementing Schema 1 (Choose Program) -> 2 (Open Samples/Cmds) -> 3 (Functions)."""

    def __init__(
        self,
        controller: ArtDirectorController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Aggiungi Programma — Procedura Guidata (1-2-3)")
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(
                min(720, int(avail.width() * 0.85)),
                max(480, min(640, int(avail.height() * 0.80))),
            )
        else:
            self.resize(700, 620)

        self._profile: ProgramProfile | None = None
        self._installed: list[InstalledProgram] = []
        self._temp_functions = []

        outer_root = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 4, 0)
        scroll.setWidget(body)
        outer_root.addWidget(scroll, stretch=1)

        # ---- Passo 1: Choose Program
        step1_box = QGroupBox("Passo 1 — Choose Program (Programmi Installati)")
        s1_layout = QFormLayout(step1_box)
        self.prog_filter_edit = QLineEdit()
        self.prog_filter_edit.setPlaceholderText(
            "🔍 Cerca programma (es. Reaper, Sonar, NEXO, QLC, Mixer)..."
        )
        self.prog_filter_edit.setClearButtonEnabled(True)
        self.prog_filter_edit.textChanged.connect(self._apply_program_filter)
        s1_layout.addRow("Filtra lista:", self.prog_filter_edit)

        prog_row = QHBoxLayout()
        self.prog_combo = QComboBox()
        self.prog_combo.setMaxVisibleItems(18)
        self.prog_combo.currentIndexChanged.connect(self._on_program_selected)
        refresh_btn = QPushButton("Aggiorna")
        refresh_btn.clicked.connect(self._populate_installed_programs)
        browse_btn = QPushButton("Sfoglia altro .exe...")
        browse_btn.clicked.connect(self._browse_custom_exe)
        prog_row.addWidget(self.prog_combo, stretch=1)
        prog_row.addWidget(refresh_btn)
        prog_row.addWidget(browse_btn)
        s1_layout.addRow("Programma:", prog_row)

        self.name_edit = QLineEdit()
        self.exe_edit = QLineEdit()
        self.pattern_edit = QLineEdit()
        s1_layout.addRow("Nome scheda:", self.name_edit)
        s1_layout.addRow("Eseguibile:", self.exe_edit)
        s1_layout.addRow("Titolo finestra (match):", self.pattern_edit)
        root.addWidget(step1_box)

        # ---- Passo 2: Istruzione apertura programma (Campioni Audio + Testo)
        step2_box = QGroupBox("Passo 2 — Apertura Programma (Campioni Audio + Etichetta/Prefisso)")
        s2_layout = QVBoxLayout(step2_box)

        text_row = QHBoxLayout()
        self.open_cmd_edit = QLineEdit()
        self.open_cmd_edit.setPlaceholderText("Nome/Prefisso (es: UehBerì, Mixer, Control, Berì)")
        add_open_btn = QPushButton("+ Aggiungi Etichetta")
        add_open_btn.clicked.connect(self._add_open_command)
        text_row.addWidget(self.open_cmd_edit, stretch=1)
        text_row.addWidget(add_open_btn)
        s2_layout.addLayout(text_row)

        self.open_list = QListWidget()
        self.open_list.setMaximumHeight(64)
        s2_layout.addWidget(self.open_list)

        self.open_sample_recorder = SampleRecorderWidget(
            controller=self.controller,
            label_provider=lambda: (
                self.open_cmd_edit.text().strip()
                or (
                    self.open_list.item(0).data(Qt.ItemDataRole.UserRole)
                    if self.open_list.count() > 0
                    else self.name_edit.text().strip()
                )
                or "apri_programma"
            ),
            compact=True,
            parent=self,
        )
        s2_layout.addWidget(self.open_sample_recorder)
        root.addWidget(step2_box)

        # ---- Passo 3: Istruzioni funzioni (Con applicazione aperta)
        step3_box = QGroupBox("Passo 3 — Funzioni & Macro (opzionale ora, puoi aggiungerle anche dopo)")
        s3_layout = QVBoxLayout(step3_box)
        fn_btn_row = QHBoxLayout()
        pick_fn_btn = QPushButton("🎯 Nuova Funzione / Macro (Campione 🔴 + Picking)")
        pick_fn_btn.clicked.connect(lambda: self._open_function_recorder(False))
        adv_fn_btn = QPushButton("+ Azione Avanzata (OSC / Art-Net / MIDI / Progetto)")
        adv_fn_btn.clicked.connect(lambda: self._open_function_recorder(True))
        fn_btn_row.addWidget(pick_fn_btn)
        fn_btn_row.addWidget(adv_fn_btn)
        s3_layout.addLayout(fn_btn_row)

        self.fn_preview_list = QListWidget()
        self.fn_preview_list.setMaximumHeight(88)
        s3_layout.addWidget(self.fn_preview_list)
        root.addWidget(step3_box)

        # ---- Confirm / Cancel
        bottom = QHBoxLayout()
        cancel_btn = QPushButton("Annulla")
        cancel_btn.clicked.connect(self.reject)
        done_btn = QPushButton("CONFERMA E CREA SCHEDA PROGRAMMA")
        done_btn.setMinimumHeight(40)
        done_btn.setStyleSheet(
            "QPushButton { background-color: #15803d; color: white; font-weight: 800; }"
        )
        done_btn.clicked.connect(self._on_finish)
        bottom.addStretch(1)
        bottom.addWidget(cancel_btn)
        bottom.addWidget(done_btn)
        outer_root.addLayout(bottom)

        self._populate_installed_programs()

    @property
    def created_profile(self) -> ProgramProfile | None:
        return self._profile

    def _populate_installed_programs(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._installed = discover_all_installed_programs()
            self._apply_program_filter(self.prog_filter_edit.text())
        finally:
            QApplication.restoreOverrideCursor()

    def _apply_program_filter(self, filter_text: str = "") -> None:
        q = filter_text.strip().lower()
        self.prog_combo.blockSignals(True)
        self.prog_combo.clear()
        for prog in self._installed:
            if q and q not in f"{prog.name} {Path(prog.executable).name}".lower():
                continue
            self.prog_combo.addItem(f"{prog.name}  ({Path(prog.executable).name})", prog)
        self.prog_combo.blockSignals(False)
        if self.prog_combo.count() > 0:
            self.prog_combo.setCurrentIndex(0)
            self._on_program_selected(0)

    def _on_program_selected(self, idx: int) -> None:
        prog = self.prog_combo.itemData(idx)
        if isinstance(prog, InstalledProgram):
            self.name_edit.setText(prog.name)
            self.exe_edit.setText(prog.executable)
            self.pattern_edit.setText(prog.window_title_hint or prog.name)

    def _browse_custom_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Seleziona Eseguibile Programma")
        if path:
            stem = Path(path).stem
            self.name_edit.setText(stem)
            self.exe_edit.setText(path)
            self.pattern_edit.setText(stem)

    def _add_open_command(self) -> None:
        raw = self.open_cmd_edit.text().strip()
        if not raw:
            return
        self.open_cmd_edit.clear()
        existing = {
            str(self.open_list.item(i).data(Qt.ItemDataRole.UserRole)).lower()
            for i in range(self.open_list.count())
        }
        for part in raw.split(","):
            txt = part.strip()
            if not txt or txt.lower() in existing:
                continue
            existing.add(txt.lower())
            idx = self.open_list.count() + 1
            role = "Principale" if idx == 1 else "Alias"
            item = QListWidgetItem(f"{idx}. {txt} ({role})")
            item.setData(Qt.ItemDataRole.UserRole, txt)
            self.open_list.addItem(item)

    def _build_temp_profile(self) -> ProgramProfile:
        name = self.name_edit.text().strip() or "Programma"
        exe = self.exe_edit.text().strip()
        patterns = [p.strip() for p in self.pattern_edit.text().split(",") if p.strip()]
        open_cmds: list[str] = []
        for i in range(self.open_list.count()):
            raw_item = str(self.open_list.item(i).data(Qt.ItemDataRole.UserRole))
            for part in raw_item.split(","):
                p_clean = part.strip()
                if p_clean and p_clean.lower() not in [c.lower() for c in open_cmds]:
                    open_cmds.append(p_clean)
        if not open_cmds and self.open_cmd_edit.text().strip():
            for part in self.open_cmd_edit.text().split(","):
                p_clean = part.strip()
                if p_clean:
                    open_cmds.append(p_clean)
        if not open_cmds and self.open_sample_recorder.samples:
            open_cmds.append(name)
        return ProgramProfile(
            id=name.lower().replace(" ", "_").replace("/", "_"),
            name=name,
            executable=exe,
            process_name=Path(exe).stem if exe else name,
            window_title_patterns=patterns or [name],
            open_commands=open_cmds,
            open_samples=self.open_sample_recorder.samples,
            functions=list(self._temp_functions),
        )

    def _open_function_recorder(self, start_advanced: bool) -> None:
        temp_prog = self._build_temp_profile()
        dlg = FunctionRecorderDialog(
            self.controller, temp_prog, parent=self, start_with_advanced=start_advanced
        )
        if dlg.exec() and dlg.result_data is not None:
            cmds, steps, focus, launch, samples = dlg.result_data
            temp_prog.functions = list(self._temp_functions)
            fn, merged = register_or_merge_function(
                temp_prog,
                cmds,
                steps,
                focus,
                launch,
                sample_files=samples,
                allow_without_prefix=dlg.allow_without_prefix,
            )
            self._temp_functions = list(temp_prog.functions)
            self._refresh_fn_preview()
            if merged:
                QMessageBox.information(
                    self,
                    "Alias associato automaticamente",
                    f"Controllo già presente! '{cmds[0]}' aggiunto come alias di '{fn.primary_command}'.",
                )

    def _refresh_fn_preview(self) -> None:
        self.fn_preview_list.clear()
        for fn in self._temp_functions:
            aliases = f" (alias: {', '.join(fn.aliases)})" if fn.aliases else ""
            samp = f" [🔊 {len(fn.sample_files)}]" if fn.sample_files else ""
            steps_desc = " -> ".join(s.describe() for s in fn.steps if s.kind != "wait")
            self.fn_preview_list.addItem(f"{fn.primary_command}{aliases}{samp}  =>  {steps_desc}")

    def _on_finish(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Nome mancante", "Seleziona o inserisci il nome del programma.")
            return
        prof = self._build_temp_profile()
        if not prof.open_commands and not prof.open_samples:
            QMessageBox.warning(
                self,
                "Comando apertura mancante",
                "Registra un campione audio o scrivi almeno un comando nel Passo 2.",
            )
            return
        self._profile = prof
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.open_sample_recorder.cleanup()
        super().closeEvent(event)


class ProgramTabWidget(QWidget):
    """Dynamic Settings tab generated for each user-added ProgramProfile."""

    remove_requested = Signal(str)

    def __init__(
        self,
        controller: ArtDirectorController,
        profile: ProgramProfile,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.profile = profile

        layout = QVBoxLayout(self)

        # ---- Program Metadata & Boot Launcher
        meta_box = QGroupBox(f"Configurazione Programma — {profile.name}")
        form = QFormLayout(meta_box)
        exe_row = QHBoxLayout()
        self.exe_edit = QLineEdit(profile.executable)
        exe_btn = QPushButton("Sfoglia...")
        exe_btn.clicked.connect(self._browse_exe)
        exe_row.addWidget(self.exe_edit)
        exe_row.addWidget(exe_btn)
        form.addRow("Eseguibile:", exe_row)

        self.patterns_edit = QLineEdit(", ".join(profile.window_title_patterns))
        form.addRow("Titolo Finestra:", self.patterns_edit)

        boot_row = QHBoxLayout()
        self.enabled_chk = QCheckBox("Abilitato")
        self.enabled_chk.setChecked(profile.enabled)
        self.startup_chk = QCheckBox("Avvia all'accensione / Avvia Tutto")
        self.startup_chk.setChecked(profile.launch_on_startup)
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 20.0)
        self.delay_spin.setValue(profile.startup_delay_sec)
        boot_row.addWidget(self.enabled_chk)
        boot_row.addWidget(self.startup_chk)
        boot_row.addWidget(QLabel("Attesa (s):"))
        boot_row.addWidget(self.delay_spin)
        form.addRow("Avvio:", boot_row)
        layout.addWidget(meta_box)

        # ---- Side-by-side Columns: Opening / Samples (Left) | Functions Table (Right)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        # ---- Left Column: Opening / Prefix Commands + Audio Samples (Step 2)
        open_box = QGroupBox("Apertura Programma (Campioni Audio + Comandi/Prefissi)")
        open_layout = QVBoxLayout(open_box)
        open_add_row = QHBoxLayout()
        self.open_input = QLineEdit()
        self.open_input.setPlaceholderText("Etichetta / prefisso testo (es: UehBerì)...")
        add_open_btn = QPushButton("+ Aggiungi")
        add_open_btn.clicked.connect(self._add_open_cmd)
        del_open_btn = QPushButton("Rimuovi")
        del_open_btn.clicked.connect(self._remove_open_cmd)
        open_add_row.addWidget(self.open_input, stretch=1)
        open_add_row.addWidget(add_open_btn)
        open_add_row.addWidget(del_open_btn)
        open_layout.addLayout(open_add_row)

        self.open_list = QListWidget()
        self.open_list.setMinimumHeight(44)
        self.open_list.setMaximumHeight(88)
        open_layout.addWidget(self.open_list)

        self.open_sample_recorder = SampleRecorderWidget(
            controller=self.controller,
            label_provider=lambda: (
                self.profile.primary_open_command or self.profile.name
            ),
            initial_samples=self.profile.open_samples,
            compact=True,
            expand_list=True,
            parent=self,
        )
        open_layout.addWidget(self.open_sample_recorder, stretch=1)
        splitter.addWidget(open_box)

        # ---- Right Column: Functions, Macros & Advanced Actions (Step 3)
        fn_box = QGroupBox("Funzioni Pickate, Campioni Audio, Sequenze Macro & Azioni Avanzate")
        fn_layout = QVBoxLayout(fn_box)
        fn_toolbar_top = QHBoxLayout()
        add_pick_btn = QPushButton("🎯 Nuova Funzione / Macro (Campione + Picking)")
        add_pick_btn.setStyleSheet(
            "QPushButton { background-color: #1d4ed8; color: white; font-weight: bold; }"
        )
        add_pick_btn.clicked.connect(lambda: self._add_function(False))
        add_adv_btn = QPushButton("+ Azione Avanzata")
        add_adv_btn.clicked.connect(lambda: self._add_function(True))
        fn_toolbar_top.addWidget(add_pick_btn)
        fn_toolbar_top.addWidget(add_adv_btn)
        fn_toolbar_top.addStretch(1)
        fn_layout.addLayout(fn_toolbar_top)

        fn_toolbar_ops = QHBoxLayout()
        edit_fn_btn = QPushButton("✏️ Modifica")
        edit_fn_btn.clicked.connect(self._edit_selected_fn)
        alias_btn = QPushButton("+ Alias Testo")
        alias_btn.clicked.connect(self._add_alias_to_selected)
        test_btn = QPushButton("▶ Testa")
        test_btn.clicked.connect(self._test_selected)
        del_fn_btn = QPushButton("Elimina")
        del_fn_btn.clicked.connect(self._delete_selected_fn)
        fn_toolbar_ops.addWidget(edit_fn_btn)
        fn_toolbar_ops.addWidget(alias_btn)
        fn_toolbar_ops.addWidget(test_btn)
        fn_toolbar_ops.addWidget(del_fn_btn)
        fn_toolbar_ops.addStretch(1)
        fn_layout.addLayout(fn_toolbar_ops)

        self.fn_table = QTableWidget(0, 4)
        self.fn_table.setMinimumHeight(200)
        self.fn_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.fn_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.fn_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.fn_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fn_table.customContextMenuRequested.connect(self._on_fn_table_context_menu)
        self.fn_table.itemDoubleClicked.connect(lambda _item: self._edit_selected_fn())
        self._del_fn_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Delete),
            self.fn_table,
            activated=self._delete_selected_fn,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )
        self.fn_table.setHorizontalHeaderLabels(
            ["Comando", "Campioni Audio", "Alias Testo", "Azioni / Sequenza"]
        )
        self.fn_table.horizontalHeader().setStretchLastSection(True)
        fn_layout.addWidget(self.fn_table, stretch=1)
        splitter.addWidget(fn_box)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([380, 620])
        layout.addWidget(splitter, stretch=1)

        footer = QHBoxLayout()
        remove_prog_btn = QPushButton(f"🗑️ Rimuovi '{profile.name}' dai Settings")
        remove_prog_btn.setStyleSheet("QPushButton { color: #fca5a5; }")
        remove_prog_btn.clicked.connect(lambda: self.remove_requested.emit(self.profile.id))
        footer.addStretch(1)
        footer.addWidget(remove_prog_btn)
        layout.addLayout(footer)

        self._refresh_open_list()
        self._refresh_fn_table()

    def _browse_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f"Seleziona eseguibile {self.profile.name}")
        if path:
            self.exe_edit.setText(path)

    def _add_open_cmd(self) -> None:
        raw = self.open_input.text().strip()
        if not raw:
            return
        self.open_input.clear()
        added = False
        existing = {c.lower() for c in self.profile.open_commands}
        for part in raw.split(","):
            txt = part.strip()
            if txt and txt.lower() not in existing:
                self.profile.open_commands.append(txt)
                existing.add(txt.lower())
                added = True
        if added:
            self._refresh_open_list()

    def _remove_open_cmd(self) -> None:
        row = self.open_list.currentRow()
        if 0 <= row < len(self.profile.open_commands):
            self.profile.open_commands.pop(row)
            self._refresh_open_list()

    def _refresh_open_list(self) -> None:
        self.open_list.clear()
        for idx, cmd in enumerate(self.profile.open_commands, start=1):
            role = "Principale" if idx == 1 else "Alias"
            self.open_list.addItem(f"{idx}. {cmd} ({role})")

    def _add_function(self, start_advanced: bool) -> None:
        self.apply_to_profile()
        dlg = FunctionRecorderDialog(
            self.controller, self.profile, parent=self, start_with_advanced=start_advanced
        )
        if dlg.exec() and dlg.result_data is not None:
            cmds, steps, focus, launch, samples = dlg.result_data
            fn, merged = register_or_merge_function(
                self.profile,
                cmds,
                steps,
                focus,
                launch,
                sample_files=samples,
                allow_without_prefix=dlg.allow_without_prefix,
            )
            self._refresh_fn_table()
            if merged:
                QMessageBox.information(
                    self,
                    "Alias associato automaticamente",
                    f"Controllo già pickato! '{cmds[0]}' e i nuovi campioni sono stati aggiunti a '{fn.primary_command}'.",
                )

    def _edit_selected_fn(self) -> None:
        row = self.fn_table.currentRow()
        if not (0 <= row < len(self.profile.functions)):
            return
        self.apply_to_profile()
        fn = self.profile.functions[row]
        dlg = FunctionRecorderDialog(
            self.controller,
            self.profile,
            parent=self,
            existing_function=fn,
        )
        if dlg.exec() and dlg.result_data is not None:
            cmds, steps, focus, launch, samples = dlg.result_data
            merged_cmds = [cmds[0]]
            for a in fn.aliases:
                if a.lower() != cmds[0].lower() and a.lower() not in [c.lower() for c in merged_cmds]:
                    merged_cmds.append(a)
            fn.commands = merged_cmds
            fn.steps = steps
            fn.signature = compute_function_signature(steps)
            fn.focus_before_run = focus
            fn.launch_if_closed = launch
            fn.allow_without_prefix = dlg.allow_without_prefix
            fn.sample_files = samples
            self._refresh_fn_table()

    def _add_alias_to_selected(self) -> None:
        row = self.fn_table.currentRow()
        if not (0 <= row < len(self.profile.functions)):
            return
        fn = self.profile.functions[row]
        txt, ok = QInputDialog.getText(
            self, "Nuovo Alias", f"Aggiungi alias testo per '{fn.primary_command}':"
        )
        if ok and txt.strip():
            if txt.strip().lower() not in [c.lower() for c in fn.commands]:
                fn.commands.append(txt.strip())
                self._refresh_fn_table()

    def _test_selected(self) -> None:
        row = self.fn_table.currentRow()
        if not (0 <= row < len(self.profile.functions)):
            return
        self.apply_to_profile()
        fn = self.profile.functions[row]
        params: dict[str, str] = {}
        if any(s.kind == "open_project" and s.use_spoken_param for s in fn.steps):
            val, ok = QInputDialog.getText(
                self,
                "Test comando con {nome}",
                f"Inserisci un nome per {{nome}} (es. Money) per testare '{fn.primary_command}':",
            )
            if not ok:
                return
            if val.strip():
                params["nome"] = val.strip()

        needs_gui = any(
            s.kind
            in (
                "click",
                "double_click",
                "right_click",
                "scroll_up",
                "scroll_down",
                "hotkey",
                "hotkey_if_dialog",
            )
            for s in fn.steps
        )
        host_win = self.window() if needs_gui else None
        was_visible = bool(host_win and host_win.isVisible())
        if was_visible and host_win is not None:
            host_win.hide()
            QApplication.processEvents()
        try:
            res = self.controller.program_executor.execute_function(
                self.profile, fn, params, CancellationToken()
            )
        finally:
            if was_visible and host_win is not None:
                host_win.show()
                host_win.raise_()
                host_win.activateWindow()
        QMessageBox.information(self, "Risultato Test", res.summary)

    def _delete_selected_fn(self) -> None:
        row = self.fn_table.currentRow()
        if 0 <= row < len(self.profile.functions):
            self.profile.functions.pop(row)
            self._refresh_fn_table()

    def _on_fn_table_context_menu(self, pos) -> None:
        item = self.fn_table.itemAt(pos)
        if item is not None:
            self.fn_table.setCurrentCell(item.row(), 0)
        row = self.fn_table.currentRow()
        if not (0 <= row < len(self.profile.functions)):
            return
        menu = QMenu(self)
        act_edit = menu.addAction("✏️ Modifica funzione")
        act_test = menu.addAction("▶ Testa")
        menu.addSeparator()
        act_del = menu.addAction("🗑️ Elimina funzione (Canc)")
        chosen = menu.exec(self.fn_table.viewport().mapToGlobal(pos))
        if chosen == act_edit:
            self._edit_selected_fn()
        elif chosen == act_test:
            self._test_selected()
        elif chosen == act_del:
            self._delete_selected_fn()

    def _refresh_fn_table(self) -> None:
        self.fn_table.setRowCount(len(self.profile.functions))
        for row_i, fn in enumerate(self.profile.functions):
            cmd_label = (
                f"{fn.primary_command} [senza prefisso]"
                if fn.allow_without_prefix
                else fn.primary_command
            )
            self.fn_table.setItem(row_i, 0, QTableWidgetItem(cmd_label))
            samp_str = (
                f"🔊 {len(fn.sample_files)} (" + ", ".join(Path(s).name for s in fn.sample_files[:2]) + ")"
                if fn.sample_files
                else "0"
            )
            self.fn_table.setItem(row_i, 1, QTableWidgetItem(samp_str))
            self.fn_table.setItem(row_i, 2, QTableWidgetItem(", ".join(fn.aliases)))
            steps_desc = " -> ".join(s.describe() for s in fn.steps if s.kind != "wait")
            self.fn_table.setItem(row_i, 3, QTableWidgetItem(steps_desc))
        self.fn_table.resizeColumnsToContents()

    def apply_to_profile(self) -> ProgramProfile:
        self.profile.executable = self.exe_edit.text().strip()
        if self.profile.executable:
            self.profile.process_name = Path(self.profile.executable).stem
        self.profile.window_title_patterns = [
            p.strip() for p in self.patterns_edit.text().split(",") if p.strip()
        ]
        self.profile.enabled = self.enabled_chk.isChecked()
        self.profile.launch_on_startup = self.startup_chk.isChecked()
        self.profile.startup_delay_sec = self.delay_spin.value()
        self.profile.open_samples = self.open_sample_recorder.samples
        return self.profile

    def cleanup(self) -> None:
        self.open_sample_recorder.cleanup()
