"""Clean dynamic Settings dialog: 4 core tabs + dynamic ProgramProfile tabs."""

from __future__ import annotations

import copy
import os
import threading
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..audio.devices import list_input_devices
from ..config.manager import (
    build_subset_config,
    export_config_file,
    get_app_base_dir,
    get_configs_dir,
    get_default_config_dir,
    get_samples_dir,
    import_config_file,
    is_portable_mode,
    list_saved_configs,
    merge_loaded_config,
    sanitize_profile_filename,
)
from ..config.schema import AppConfig, ProgramProfile
from ..core.controller import ArtDirectorController
from ..os_layer.hotkeys import format_hotkey_display, normalize_pynput_hotkey
from ..os_layer.installer import (
    enable_portable_mode,
    install_on_system,
    is_installed_on_system,
    uninstall_from_system,
)
from ..stt.manager import discover_local_models
from ..stt.vosk_engine import is_valid_vosk_model_dir
from ..stt.whisper_engine import is_valid_whisper_model_dir
from .program_wizard import (
    AddProgramWizardDialog,
    ProgramTabWidget,
    SafeModalDialog,
    SampleRecorderWidget,
)


def _join_csv(items: list[str]) -> str:
    return ", ".join(items)


def _split_csv(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


_QT_MODIFIER_KEYS = {
    int(Qt.Key.Key_Control),
    int(Qt.Key.Key_Shift),
    int(Qt.Key.Key_Alt),
    int(Qt.Key.Key_AltGr),
    int(Qt.Key.Key_Meta),
    int(Qt.Key.Key_Super_L),
    int(Qt.Key.Key_Super_R),
    int(Qt.Key.Key_Menu),
}

_QT_KEY_TOKEN_MAP = {
    int(Qt.Key.Key_Escape): "<esc>",
    int(Qt.Key.Key_Return): "<enter>",
    int(Qt.Key.Key_Enter): "<enter>",
    int(Qt.Key.Key_Space): "<space>",
    int(Qt.Key.Key_Tab): "<tab>",
    int(Qt.Key.Key_Backtab): "<tab>",
    int(Qt.Key.Key_Backspace): "<backspace>",
    int(Qt.Key.Key_Delete): "<delete>",
    int(Qt.Key.Key_Insert): "<insert>",
    int(Qt.Key.Key_Home): "<home>",
    int(Qt.Key.Key_End): "<end>",
    int(Qt.Key.Key_PageUp): "<page_up>",
    int(Qt.Key.Key_PageDown): "<page_down>",
    int(Qt.Key.Key_Up): "<up>",
    int(Qt.Key.Key_Down): "<down>",
    int(Qt.Key.Key_Left): "<left>",
    int(Qt.Key.Key_Right): "<right>",
    int(Qt.Key.Key_Pause): "<pause>",
    int(Qt.Key.Key_ScrollLock): "<scroll_lock>",
    int(Qt.Key.Key_CapsLock): "<caps_lock>",
    int(Qt.Key.Key_NumLock): "<num_lock>",
    int(Qt.Key.Key_Print): "<print_screen>",
    int(Qt.Key.Key_SysReq): "<print_screen>",
    int(Qt.Key.Key_Plus): "<plus>",
    int(Qt.Key.Key_Minus): "-",
}


def qt_key_to_pynput_hotkey(
    key: int, modifiers: Qt.KeyboardModifier | int, text: str = ""
) -> str:
    """Convert a Qt key + modifiers into normalized Art Director pynput hotkey syntax."""
    k = int(key)
    if k in _QT_MODIFIER_KEYS or k == 0 or k == int(Qt.Key.Key_unknown):
        return ""

    mods = Qt.KeyboardModifier(modifiers)
    parts: list[str] = []
    if mods & Qt.KeyboardModifier.ControlModifier:
        parts.append("<ctrl>")
    if mods & Qt.KeyboardModifier.AltModifier:
        parts.append("<alt>")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        parts.append("<shift>")
    if mods & Qt.KeyboardModifier.MetaModifier:
        parts.append("<cmd>")

    token = _QT_KEY_TOKEN_MAP.get(k)
    if token is None:
        f1 = int(Qt.Key.Key_F1)
        f12 = int(Qt.Key.Key_F12)
        if f1 <= k <= f12:
            token = f"<f{k - f1 + 1}>"
        elif int(Qt.Key.Key_A) <= k <= int(Qt.Key.Key_Z):
            token = chr(k).lower()
        elif int(Qt.Key.Key_0) <= k <= int(Qt.Key.Key_9):
            token = chr(k)
        elif 0x21 <= k <= 0x7E:
            token = chr(k).lower()
        else:
            t_clean = text.strip().lower()
            if len(t_clean) == 1 and t_clean.isprintable():
                token = t_clean
    if not token:
        return ""
    parts.append(token)
    return normalize_pynput_hotkey("+".join(parts))


class _HotkeyCaptureBox(QLabel):
    """Focusable box that intercepts any key press (including Esc, Tab, Enter, Space)."""

    def __init__(self, on_captured, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_captured = on_captured
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumHeight(86)
        self.setStyleSheet(
            "QLabel { background-color: #0f172a; border: 2px solid #3b82f6; border-radius: 8px; "
            "color: #f8fafc; font-size: 15px; font-weight: 700; padding: 12px; }"
            "QLabel:focus { border-color: #22c55e; background-color: #111c33; }"
        )
        self.set_preview("")

    def set_preview(self, hotkey: str) -> None:
        pretty = format_hotkey_display(hotkey)
        if pretty:
            self.setText(
                f"⌨️  {pretty}\n"
                f"<span style='font-size:11px; color:#93c5fd; font-weight:normal;'>"
                f"Codice: {hotkey} · Premi un altro tasto per cambiare</span>"
            )
        else:
            self.setText(
                "🎹 Premi ora il tasto o la combinazione desiderata...\n"
                "<span style='font-size:11px; color:#9fb3d9; font-weight:normal;'>"
                "Es. Ctrl+Esc, Alt+-, F12, Pausa, BlocScorr, Ctrl+Spazio</span>"
            )

    def event(self, ev) -> bool:  # noqa: A003
        if ev.type() == QEvent.Type.ShortcutOverride:
            ev.accept()
            return True
        if ev.type() == QEvent.Type.KeyPress:
            assert isinstance(ev, QKeyEvent)
            combo = qt_key_to_pynput_hotkey(ev.key(), ev.modifiers(), ev.text())
            if combo:
                self._on_captured(combo)
            else:
                # Show held modifiers live while user reaches for the main key
                mods = ev.modifiers()
                held = []
                if mods & Qt.KeyboardModifier.ControlModifier:
                    held.append("Ctrl")
                if mods & Qt.KeyboardModifier.AltModifier:
                    held.append("Alt")
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    held.append("Shift")
                if mods & Qt.KeyboardModifier.MetaModifier:
                    held.append("Win")
                if held:
                    self.setText(f"⌨️  {' + '.join(held)} + ...")
            ev.accept()
            return True
        return super().event(ev)


class HotkeyCaptureDialog(SafeModalDialog):
    """Clean dialog to capture a real keyboard shortcut with live preview & conflict warning."""

    def __init__(
        self,
        action_title: str,
        current_hotkey: str = "",
        other_hotkeys: dict[str, str] | None = None,
        controller: ArtDirectorController | None = None,
        hint_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._other_hotkeys = {
            k: normalize_pynput_hotkey(v)
            for k, v in (other_hotkeys or {}).items()
            if v and normalize_pynput_hotkey(v)
        }
        self.captured_hotkey: str = normalize_pynput_hotkey(current_hotkey)
        self.cleared: bool = False

        self.setWindowTitle(f"⌨️ Assegna Shortcut — {action_title}")
        self.resize(470, 290)
        root = QVBoxLayout(self)
        root.setSpacing(10)

        desc = QLabel(
            hint_text
            or f"Premi sulla tastiera il tasto o la combinazione globale da assegnare a <b>{action_title}</b>.<br>"
            "Funziona anche mentre usi X-AIR Edit, Sonar, QLC+ o VirtualDJ."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #cbd5e1;")
        root.addWidget(desc)

        self.capture_box = _HotkeyCaptureBox(self._on_box_captured, parent=self)
        self.capture_box.set_preview(self.captured_hotkey)
        root.addWidget(self.capture_box)

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Sintassi manuale:"))
        self.manual_edit = QLineEdit(self.captured_hotkey)
        self.manual_edit.setPlaceholderText("es. <ctrl>+<esc>, <alt>+-, <f12>, <pause>")
        self.manual_edit.textEdited.connect(self._on_manual_edited)
        manual_row.addWidget(self.manual_edit, stretch=1)
        root.addLayout(manual_row)

        self.conflict_lbl = QLabel()
        self.conflict_lbl.setWordWrap(True)
        self.conflict_lbl.setStyleSheet("color: #fbbf24; font-size: 11px;")
        root.addWidget(self.conflict_lbl)
        self._refresh_conflict_warning()

        btns = QHBoxLayout()
        clear_btn = QPushButton("🗑️ Rimuovi Shortcut")
        clear_btn.setAutoDefault(False)
        clear_btn.setDefault(False)
        clear_btn.clicked.connect(self._on_clear)

        cancel_btn = QPushButton("Annulla")
        cancel_btn.setAutoDefault(False)
        cancel_btn.setDefault(False)
        cancel_btn.clicked.connect(self.reject)

        apply_btn = QPushButton("✅ Applica Shortcut")
        apply_btn.setAutoDefault(False)
        apply_btn.setDefault(False)
        apply_btn.setStyleSheet(
            "QPushButton { background-color: #15803d; color: white; font-weight: 700; padding: 7px 14px; }"
            "QPushButton:hover { background-color: #16a34a; }"
        )
        apply_btn.clicked.connect(self._on_apply)

        btns.addWidget(clear_btn)
        btns.addStretch(1)
        btns.addWidget(cancel_btn)
        btns.addWidget(apply_btn)
        root.addLayout(btns)
        self.capture_box.setFocus()

    def exec(self) -> int:  # noqa: A003
        # Pause existing global hotkeys while capturing so pressing current Panic/Wake doesn't fire it
        had_hotkeys = False
        if self._controller is not None and getattr(self._controller, "_enable_hotkeys", False):
            had_hotkeys = True
            self._controller.hotkeys.stop()
        try:
            self.capture_box.setFocus()
            return super().exec()
        finally:
            if had_hotkeys and self._controller is not None:
                self._controller._register_hotkeys()

    def _on_box_captured(self, combo: str) -> None:
        self.captured_hotkey = combo
        self.cleared = False
        self.manual_edit.blockSignals(True)
        self.manual_edit.setText(combo)
        self.manual_edit.blockSignals(False)
        self.capture_box.set_preview(combo)
        self._refresh_conflict_warning()

    def _on_manual_edited(self, text: str) -> None:
        norm = normalize_pynput_hotkey(text)
        self.captured_hotkey = norm
        self.cleared = not bool(norm)
        self.capture_box.set_preview(norm)
        self._refresh_conflict_warning()

    def _refresh_conflict_warning(self) -> None:
        if not self.captured_hotkey:
            self.conflict_lbl.setText("")
            return
        conflicts = [
            name for name, hk in self._other_hotkeys.items() if hk == self.captured_hotkey
        ]
        if conflicts:
            self.conflict_lbl.setText(
                f"⚠️ Attenzione: questa combinazione è già usata per {', '.join(conflicts)}."
            )
        else:
            self.conflict_lbl.setText("")

    def _on_clear(self) -> None:
        self.captured_hotkey = ""
        self.cleared = True
        self.accept()

    def _on_apply(self) -> None:
        raw = self.manual_edit.text().strip()
        self.captured_hotkey = normalize_pynput_hotkey(raw)
        self.cleared = not bool(self.captured_hotkey)
        if self.captured_hotkey:
            conflicts = [
                name for name, hk in self._other_hotkeys.items() if hk == self.captured_hotkey
            ]
            if conflicts:
                ans = QMessageBox.question(
                    self,
                    "Shortcut già assegnata",
                    f"La shortcut '{format_hotkey_display(self.captured_hotkey)}' è già assegnata a "
                    f"{', '.join(conflicts)}.\nVuoi usarla lo stesso qui?",
                )
                if ans != QMessageBox.StandardButton.Yes:
                    return
        self.accept()


class SaveConfigProfileDialog(SafeModalDialog):
    """Export / save a full or subset configuration (.json preset or portable .zip)."""

    def __init__(
        self,
        config: AppConfig,
        configs_dir: Path,
        samples_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._configs_dir = Path(configs_dir)
        self._samples_dir = Path(samples_dir)
        self._manual_name = False
        self.saved_path: Path | None = None
        self.exported_samples: int = 0
        self.profile_name: str = ""
        self.selected_program_ids: set[str] = set()

        self.setWindowTitle("💾 Salva Configurazione / Profilo Setup")
        self.resize(560, 480)
        root = QVBoxLayout(self)

        intro = QLabel(
            "Salva una configurazione completa oppure solo alcune applicazioni (es. solo VirtualDJ + QLC+ "
            "oppure solo X-AIR + Sonar) per richiamarla rapidamente senza tenere tutto nei Settings."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9fb3d9;")
        root.addWidget(intro)

        form = QFormLayout()
        default_name = (
            config.general.active_profile_name.strip()
            or self._suggest_name([p.name for p in config.programs])
        )
        self.name_edit = QLineEdit(default_name)
        self.name_edit.textEdited.connect(lambda _t: setattr(self, "_manual_name", True))
        form.addRow("Nome Configurazione:", self.name_edit)
        root.addLayout(form)

        prog_box = QGroupBox("Applicazioni da includere in questo file:")
        prog_layout = QVBoxLayout(prog_box)
        quick_row = QHBoxLayout()
        sel_all_btn = QPushButton("Seleziona Tutti")
        sel_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        sel_none_btn = QPushButton("Deseleziona Tutti")
        sel_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        quick_row.addWidget(sel_all_btn)
        quick_row.addWidget(sel_none_btn)
        quick_row.addStretch(1)
        prog_layout.addLayout(quick_row)

        self.prog_list = QListWidget()
        for prog in config.programs:
            s_cnt = len(prog.open_samples) + sum(len(fn.sample_files) for fn in prog.functions)
            item = QListWidgetItem(
                f"{prog.name}  ({len(prog.functions)} funzioni · {s_cnt} campioni)"
            )
            item.setData(Qt.ItemDataRole.UserRole, (prog.id, prog.name))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.prog_list.addItem(item)
        if not config.programs:
            empty_item = QListWidgetItem("(Nessun programma dinamico ancora configurato)")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.prog_list.addItem(empty_item)
        self.prog_list.itemChanged.connect(self._on_program_check_changed)
        prog_layout.addWidget(self.prog_list)
        root.addWidget(prog_box, stretch=1)

        fmt_box = QGroupBox("Formato file:")
        fmt_layout = QVBoxLayout(fmt_box)
        self.radio_json = QRadioButton(
            "Profilo rapido (.json in 'configurazioni/' — usa i campioni .wav locali, cambio istantaneo)"
        )
        self.radio_zip = QRadioButton(
            "Pacchetto portatile completo (.zip — include config.json + campioni .wav per backup / altro PC / GitHub)"
        )
        self.radio_json.setChecked(True)
        fmt_layout.addWidget(self.radio_json)
        fmt_layout.addWidget(self.radio_zip)
        root.addWidget(fmt_box)

        btns = QHBoxLayout()
        cancel_btn = QPushButton("Annulla")
        cancel_btn.clicked.connect(self.reject)
        self.browse_btn = QPushButton("📁 Scegli cartella (Sfoglia...)...")
        self.browse_btn.clicked.connect(self._save_browse)
        self.save_preset_btn = QPushButton("💾 Salva in 'configurazioni/'")
        self.save_preset_btn.setStyleSheet(
            "QPushButton { background-color: #15803d; color: white; font-weight: 700; padding: 7px 14px; }"
            "QPushButton:hover { background-color: #16a34a; }"
        )
        self.save_preset_btn.clicked.connect(self._save_to_presets)
        btns.addWidget(cancel_btn)
        btns.addStretch(1)
        btns.addWidget(self.browse_btn)
        btns.addWidget(self.save_preset_btn)
        root.addLayout(btns)

    @staticmethod
    def _suggest_name(names: list[str]) -> str:
        if not names:
            return "Setup_Base"
        if len(names) <= 2:
            return " + ".join(names)
        return f"Setup_{len(names)}_App"

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.prog_list.count()):
            item = self.prog_list.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(state)

    def _on_program_check_changed(self, _item: QListWidgetItem) -> None:
        if self._manual_name:
            return
        names = [
            item.data(Qt.ItemDataRole.UserRole)[1]
            for i in range(self.prog_list.count())
            for item in [self.prog_list.item(i)]
            if (item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
            and item.checkState() == Qt.CheckState.Checked
        ]
        self.name_edit.setText(self._suggest_name(names))

    def _selected_ids(self) -> set[str]:
        ids: set[str] = set()
        for i in range(self.prog_list.count()):
            item = self.prog_list.item(i)
            if (item.flags() & Qt.ItemFlag.ItemIsUserCheckable) and (
                item.checkState() == Qt.CheckState.Checked
            ):
                ids.add(str(item.data(Qt.ItemDataRole.UserRole)[0]))
        return ids

    def _write_target(self, dest_path: Path) -> None:
        name = self.name_edit.text().strip() or dest_path.stem
        sel_ids = self._selected_ids()
        subset = build_subset_config(
            self._config,
            selected_program_ids=sel_ids if self._config.programs else None,
            profile_name=name,
        )
        out_path, sample_cnt = export_config_file(
            subset, dest_path, samples_dir=self._samples_dir
        )
        self.saved_path = out_path
        self.exported_samples = sample_cnt
        self.profile_name = name
        self.selected_program_ids = sel_ids
        self.accept()

    def _save_to_presets(self) -> None:
        ext = ".zip" if self.radio_zip.isChecked() else ".json"
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Nome mancante", "Inserisci un nome per la configurazione.")
            return
        self._configs_dir.mkdir(parents=True, exist_ok=True)
        fname = sanitize_profile_filename(name, ext=ext)
        target = self._configs_dir / fname
        if target.exists():
            ans = QMessageBox.question(
                self,
                "Sovrascrivere?",
                f"Esiste già '{target.name}' in 'configurazioni/'. Vuoi sovrascriverlo?",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        self._write_target(target)

    def _save_browse(self) -> None:
        ext = ".zip" if self.radio_zip.isChecked() else ".json"
        suggested = self._configs_dir / sanitize_profile_filename(
            self.name_edit.text().strip() or "Setup_ArtDirector", ext=ext
        )
        filt = (
            "Pacchetto Configurazione ArtDirector (*.zip);;File Configurazione JSON (*.json)"
            if ext == ".zip"
            else "File Configurazione JSON (*.json);;Pacchetto Configurazione ArtDirector (*.zip)"
        )
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Esporta Configurazione", str(suggested), filt
        )
        if not chosen:
            return
        self._write_target(Path(chosen))


class LoadConfigProfileDialog(SafeModalDialog):
    """Choose a saved preset from 'configurazioni/' or import any .json / .zip file."""

    def __init__(
        self,
        current_config: AppConfig,
        configs_dir: Path,
        samples_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._current_config = current_config
        self._configs_dir = Path(configs_dir)
        self._samples_dir = Path(samples_dir)
        self.loaded_config: AppConfig | None = None
        self.loaded_path: Path | None = None
        self.extracted_samples: int = 0
        self.loaded_profile_name: str = ""

        self.setWindowTitle("📂 Carica Configurazione / Profilo Setup")
        self.resize(620, 440)
        root = QVBoxLayout(self)

        hint = QLabel(
            f"Configurazioni salvate in <code>{self._configs_dir}</code> "
            "(fai doppio clic su un profilo oppure sfoglia un file esterno):"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9fb3d9;")
        root.addWidget(hint)

        self.preset_list = QListWidget()
        self.preset_list.itemDoubleClicked.connect(lambda _it: self._load_selected())
        root.addWidget(self.preset_list, stretch=1)

        self.keep_audio_chk = QCheckBox(
            "Mantieni Microfono, Audio (Gain/Gate), Tray e motore STT attuali "
            "(consigliato per non alterare l'ingresso microfonico)"
        )
        self.keep_audio_chk.setChecked(True)
        root.addWidget(self.keep_audio_chk)

        btns = QHBoxLayout()
        self.browse_btn = QPushButton("📁 Sfoglia file (.json / .zip)...")
        self.browse_btn.clicked.connect(self._browse_file)
        self.del_btn = QPushButton("🗑️ Elimina")
        self.del_btn.clicked.connect(self._delete_selected)
        cancel_btn = QPushButton("Annulla")
        cancel_btn.clicked.connect(self.reject)
        self.load_btn = QPushButton("📂 Carica Configurazione")
        self.load_btn.setStyleSheet(
            "QPushButton { background-color: #1d4ed8; color: white; font-weight: 700; padding: 7px 14px; }"
            "QPushButton:hover { background-color: #2563eb; }"
        )
        self.load_btn.clicked.connect(self._load_selected)

        btns.addWidget(self.browse_btn)
        btns.addWidget(self.del_btn)
        btns.addStretch(1)
        btns.addWidget(cancel_btn)
        btns.addWidget(self.load_btn)
        root.addLayout(btns)

        self._refresh_list()

    def _refresh_list(self) -> None:
        self.preset_list.clear()
        presets = list_saved_configs(self._configs_dir)
        active_name = self._current_config.general.active_profile_name.strip().lower()
        for info in presets:
            fmt = "ZIP" if info["is_zip"] else "JSON"
            progs_str = ", ".join(info["programs"]) if info["programs"] else "Nessuna app"
            active_tag = "  ★ ATTIVA" if active_name and info["name"].lower() == active_name else ""
            item = QListWidgetItem(
                f"📋 {info['name']} [{fmt}]{active_tag}  —  {progs_str} "
                f"({info['function_count']} funzioni · {info['sample_count']} campioni)"
            )
            item.setData(Qt.ItemDataRole.UserRole, info)
            self.preset_list.addItem(item)
        if not presets:
            placeholder = QListWidgetItem(
                "(Nessun file in 'configurazioni/'. Premi '💾 Salva Config...' per crearne uno o '📁 Sfoglia file...'.)"
            )
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.preset_list.addItem(placeholder)
            self.load_btn.setEnabled(False)
            self.del_btn.setEnabled(False)
        else:
            self.preset_list.setCurrentRow(0)
            self.load_btn.setEnabled(True)
            self.del_btn.setEnabled(True)

    def _apply_file(self, src_path: Path, profile_label: str = "") -> None:
        try:
            imported, extracted = import_config_file(
                src_path, samples_dir=self._samples_dir
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Errore caricamento configurazione",
                f"Impossibile leggere '{src_path.name}':\n{exc}",
            )
            return
        name = (
            profile_label.strip()
            or imported.general.active_profile_name.strip()
            or src_path.stem.replace("_", " ")
        )
        merged = merge_loaded_config(
            imported,
            self._current_config,
            keep_audio_and_stt=self.keep_audio_chk.isChecked(),
            profile_name=name,
        )
        self.loaded_config = merged
        self.loaded_path = src_path
        self.extracted_samples = extracted
        self.loaded_profile_name = name
        self.accept()

    def _load_selected(self) -> None:
        item = self.preset_list.currentItem()
        if item is None:
            return
        info = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(info, dict):
            return
        self._apply_file(Path(info["path"]), profile_label=str(info["name"]))

    def _browse_file(self) -> None:
        start_dir = str(self._configs_dir if self._configs_dir.exists() else get_default_config_dir())
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Seleziona Configurazione ArtDirector",
            start_dir,
            "Configurazioni ArtDirector (*.json *.zip);;File JSON (*.json);;Pacchetti ZIP (*.zip)",
        )
        if chosen:
            self._apply_file(Path(chosen))

    def _delete_selected(self) -> None:
        item = self.preset_list.currentItem()
        if item is None:
            return
        info = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(info, dict):
            return
        target = Path(info["path"])
        ans = QMessageBox.question(
            self,
            "Elimina configurazione salvata",
            f"Eliminare il preset '{info['name']}' ({target.name})?",
        )
        if ans == QMessageBox.StandardButton.Yes:
            try:
                target.unlink(missing_ok=True)
            except OSError as exc:
                QMessageBox.warning(self, "Errore eliminazione", str(exc))
            self._refresh_list()


class SystemSettingsPanel(QWidget):
    """Reusable 4-tab system settings panel embedded in MainWindow."""

    def __init__(
        self,
        controller: ArtDirectorController,
        on_load_config=None,
        on_save_config_as=None,
        on_settings_saved=None,
        show_save_bar: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._on_load_config_cb = on_load_config
        self._on_save_config_as_cb = on_save_config_as
        self._on_settings_saved_cb = on_settings_saved
        self._tab_scrolls: dict[int, QScrollArea] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        self.tabs = QTabWidget(self)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setStyleSheet(
            "QTabBar::tab { padding: 6px 10px; font-size: 12px; }"
        )
        root.addWidget(self.tabs, stretch=1)

        cfg = copy.deepcopy(controller.config)
        self._build_general_tab(cfg)
        self._build_sleep_panic_tab(cfg)
        self._build_audio_tab(cfg)
        self._build_stt_tab(cfg)

        if show_save_bar:
            bar = QHBoxLayout()
            self.status_hint_lbl = QLabel(
                "Modifiche di sistema pronte — premi Salva per applicare."
            )
            self.status_hint_lbl.setStyleSheet("color: #9fb3d9; font-size: 11px;")
            self.save_btn = QPushButton("💾 Salva Impostazioni")
            self.save_btn.setMinimumHeight(34)
            self.save_btn.setStyleSheet(
                "QPushButton { background-color: #15803d; color: white; font-size: 13px; font-weight: 800; padding: 6px 16px; }"
                "QPushButton:hover { background-color: #16a34a; }"
            )
            self.save_btn.clicked.connect(self._on_save_clicked)
            bar.addWidget(self.status_hint_lbl, stretch=1)
            bar.addWidget(self.save_btn)
            root.addLayout(bar)

    def _add_scrollable_tab(self, widget: QWidget, label: str) -> QScrollArea:
        scroll = QScrollArea(self.tabs)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, label)
        self._tab_scrolls[id(widget)] = scroll
        return scroll

    def _configs_dir(self) -> Path:
        return get_configs_dir(self.controller.config_manager.path.parent)

    def _samples_dir(self) -> Path:
        return self.controller.stt.samples_dir or get_samples_dir()

    def _open_configs_folder(self) -> None:
        folder = self._configs_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _refresh_active_profile_label(self, cfg: AppConfig | None = None) -> None:
        c = cfg or self.controller.config
        active_prof = c.general.active_profile_name.strip() or "Predefinita (config.json)"
        self.active_profile_label.setText(
            f"Configurazione attuale: <b>{active_prof}</b> "
            f"— Cartella preset: <code>{self._configs_dir()}</code>"
        )

    # ------------------------------------------------------------------ Tab 1
    def _build_general_tab(self, cfg: AppConfig) -> None:
        w = QWidget()
        outer = QVBoxLayout(w)

        gen_box = QGroupBox("Avvio Sistema, System Tray & Avvio Programmi")
        form = QFormLayout(gen_box)
        g = cfg.general
        sl = cfg.stage_launcher

        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["it", "en"])
        self.lang_combo.setCurrentText(g.language)
        form.addRow("Lingua principale:", self.lang_combo)

        self.min_on_close_chk = QCheckBox(
            "Chiudendo con la 'X' resta attivo nella System Tray in background"
        )
        self.min_on_close_chk.setChecked(g.minimize_on_close)
        form.addRow(self.min_on_close_chk)

        self.start_min_chk = QCheckBox("Avvia ridotto nella System Tray")
        self.start_min_chk.setChecked(g.start_minimized_to_tray)
        form.addRow(self.start_min_chk)

        self.autostart_chk = QCheckBox(
            "Avvia Art Director automaticamente al boot del Sistema Operativo"
        )
        self.autostart_chk.setChecked(g.autostart_at_os_boot)
        form.addRow(self.autostart_chk)

        self.autostart_bg_chk = QCheckBox(
            "Al boot del sistema avvia direttamente in background silenzioso (--background)"
        )
        self.autostart_bg_chk.setChecked(g.autostart_in_background)
        form.addRow(self.autostart_bg_chk)

        self.sl_auto_start_chk = QCheckBox(
            "Avvia automaticamente i programmi contrassegnati all'avvio di Art Director / Sistema"
        )
        self.sl_auto_start_chk.setChecked(sl.launch_apps_on_art_director_start)
        form.addRow(self.sl_auto_start_chk)

        self.sl_delay_spin = QDoubleSpinBox()
        self.sl_delay_spin.setRange(0.0, 30.0)
        self.sl_delay_spin.setValue(sl.initial_startup_delay_sec)
        form.addRow("Attesa iniziale dopo boot (sec):", self.sl_delay_spin)

        self.sl_all_triggers_edit = QLineEdit(_join_csv(sl.voice_launch_all_triggers))
        form.addRow("Comandi vocali 'Avvia Tutto':", self.sl_all_triggers_edit)
        self.launch_all_sample_rec = SampleRecorderWidget(
            self.controller,
            lambda: "avvia_tutto",
            initial_samples=sl.launch_all_samples,
            compact=True,
            parent=self,
        )
        form.addRow("Campioni 'Avvia Tutto' (🔴):", self.launch_all_sample_rec)
        outer.addWidget(gen_box)

        pop_box = QGroupBox("Gestione Rapida Pop-up Errore / Banner Imprevisti")
        pf = QFormLayout(pop_box)
        ph = cfg.popup_handler
        self.pop_enabled_chk = QCheckBox("Abilita comando vocale chiusura rapida Pop-up")
        self.pop_enabled_chk.setChecked(ph.enabled)
        self.pop_strategy_combo = QComboBox()
        self.pop_strategy_combo.addItems(["smart", "esc", "enter", "esc_then_close", "wm_close"])
        self.pop_strategy_combo.setCurrentText(ph.strategy)
        self.pop_triggers_edit = QLineEdit(_join_csv(ph.voice_triggers))
        self.pop_protect_chk = QCheckBox(
            "Proteggi finestre principali da chiusura accidentale"
        )
        self.pop_protect_chk.setChecked(ph.protect_main_windows)
        self.popup_sample_rec = SampleRecorderWidget(
            self.controller,
            lambda: "chiudi_popup",
            initial_samples=ph.voice_samples,
            compact=True,
            parent=self,
        )
        pf.addRow(self.pop_enabled_chk)
        pf.addRow("Strategia chiusura:", self.pop_strategy_combo)
        pf.addRow("Frasi vocali trigger:", self.pop_triggers_edit)
        pf.addRow("Campioni Pop-up (🔴):", self.popup_sample_rec)
        pf.addRow(self.pop_protect_chk)
        outer.addWidget(pop_box)

        prof_box = QGroupBox("Profili & Configurazioni Multiple (Save / Load)")
        prof_layout = QVBoxLayout(prof_box)
        self.active_profile_label = QLabel()
        self.active_profile_label.setWordWrap(True)
        self._refresh_active_profile_label(cfg)
        prof_layout.addWidget(self.active_profile_label)

        prof_btns = QHBoxLayout()
        tab_load_btn = QPushButton("📂 Carica Config...")
        tab_load_btn.clicked.connect(
            lambda: self._on_load_config_cb() if self._on_load_config_cb else None
        )
        tab_save_btn = QPushButton("💾 Salva Come...")
        tab_save_btn.clicked.connect(
            lambda: self._on_save_config_as_cb() if self._on_save_config_as_cb else None
        )
        open_cfg_dir_btn = QPushButton("📁 Cartella 'configurazioni/'")
        open_cfg_dir_btn.clicked.connect(self._open_configs_folder)
        prof_btns.addWidget(tab_load_btn)
        prof_btns.addWidget(tab_save_btn)
        prof_btns.addWidget(open_cfg_dir_btn)
        prof_layout.addLayout(prof_btns)
        outer.addWidget(prof_box)

        inst_box = QGroupBox("Installazione su PC & Modalità Portatile (Pen Drive)")
        inst_layout = QVBoxLayout(inst_box)
        mode_str = (
            "Portatile (Pen Drive / cartella locale)"
            if is_portable_mode()
            else "Profilo Utente Sistema"
        )
        self.deploy_info_label = QLabel(
            f"Modalità attuale: <b>{mode_str}</b><br>"
            f"Cartella configurazione: <code>{get_default_config_dir()}</code>"
        )
        self.deploy_info_label.setWordWrap(True)
        inst_layout.addWidget(self.deploy_info_label)

        btn_row = QHBoxLayout()
        install_btn = QPushButton("💿 Installa su PC")
        install_btn.setToolTip("Installa collegamenti su Desktop e Menu Start")
        install_btn.clicked.connect(self._on_install_system)
        portable_btn = QPushButton("🎒 Modalità Portatile")
        portable_btn.setToolTip("Attiva modalità portatile per Pen Drive")
        portable_btn.clicked.connect(self._on_enable_portable)
        uninstall_btn = QPushButton("🗑️ Disinstalla")
        uninstall_btn.setEnabled(is_installed_on_system())
        uninstall_btn.clicked.connect(self._on_uninstall_system)
        btn_row.addWidget(install_btn)
        btn_row.addWidget(portable_btn)
        btn_row.addWidget(uninstall_btn)
        inst_layout.addLayout(btn_row)
        outer.addWidget(inst_box)
        outer.addStretch(1)

        self._add_scrollable_tab(w, "Generale & Tray")

    def _on_install_system(self) -> None:
        ok, msg = install_on_system(copy_models=True)
        if ok:
            QMessageBox.information(self, "Installazione completata", msg)
        else:
            QMessageBox.warning(self, "Installazione", msg)

    def _on_enable_portable(self) -> None:
        cfg_copy = copy.deepcopy(self.controller.config)
        self.apply_to_config(cfg_copy)
        ok, msg = enable_portable_mode(cfg_copy)
        if ok:
            QMessageBox.information(self, "Modalità Portatile", msg)
        else:
            QMessageBox.warning(self, "Modalità Portatile", msg)

    def _on_uninstall_system(self) -> None:
        ans = QMessageBox.question(
            self,
            "Disinstalla Art Director",
            "Rimuovere Art Director, i collegamenti e le voci di avvio da questo PC?",
        )
        if ans == QMessageBox.StandardButton.Yes:
            _ok, msg = uninstall_from_system()
            QMessageBox.information(self, "Disinstallazione", msg)

    def _make_hotkey_row(
        self,
        edit: QLineEdit,
        action_title: str,
        others_fn,
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        capture_btn = QPushButton("🎹 Premi Tasto")
        capture_btn.setToolTip(f"Premi direttamente sulla tastiera il tasto per '{action_title}'")
        capture_btn.clicked.connect(
            lambda _=False, ed=edit, ttl=action_title, ofn=others_fn: self._capture_hotkey_into(
                ed, ttl, ofn()
            )
        )
        clear_btn = QPushButton("✖")
        clear_btn.setFixedWidth(30)
        clear_btn.setToolTip("Cancella shortcut")
        clear_btn.clicked.connect(lambda _=False, ed=edit: ed.clear())
        row.addWidget(edit, stretch=1)
        row.addWidget(capture_btn)
        row.addWidget(clear_btn)
        return row

    def _capture_hotkey_into(
        self, target_edit: QLineEdit, action_title: str, other_hotkeys: dict[str, str]
    ) -> None:
        dlg = HotkeyCaptureDialog(
            action_title=action_title,
            current_hotkey=target_edit.text(),
            other_hotkeys=other_hotkeys,
            controller=self.controller,
            parent=self,
        )
        if dlg.exec():
            target_edit.setText(dlg.captured_hotkey)

    # ------------------------------------------------------------------ Tab 2
    def _build_sleep_panic_tab(self, cfg: AppConfig) -> None:
        w = QWidget()
        layout = QVBoxLayout(w)

        sw_box = QGroupBox("Sleep Mode & Wake Mode (Dual-Mode)")
        sw_form = QFormLayout(sw_box)
        sw = cfg.sleep_wake

        self.start_sleep_chk = QCheckBox("Avvia direttamente in Sleep Mode (👋)")
        self.start_sleep_chk.setChecked(sw.start_in_sleep_mode)
        sw_form.addRow(self.start_sleep_chk)

        self.mute_in_sleep_chk = QCheckBox(
            "Disattiva microfono in Sleep Mode (riattivazione solo via Hotkey o Push-to-Talk)"
        )
        self.mute_in_sleep_chk.setChecked(sw.mute_mic_in_sleep)
        sw_form.addRow(self.mute_in_sleep_chk)

        self.sleep_kw_edit = QLineEdit(_join_csv(sw.sleep_keywords))
        self.wake_kw_edit = QLineEdit(_join_csv(sw.wake_keywords))
        self.sleep_sample_rec = SampleRecorderWidget(
            self.controller,
            lambda: "sleep_ruorm",
            initial_samples=sw.sleep_samples,
            compact=True,
            parent=self,
        )
        self.wake_sample_rec = SampleRecorderWidget(
            self.controller,
            lambda: "wake_scetat",
            initial_samples=sw.wake_samples,
            compact=True,
            parent=self,
        )
        self.sw_hotkey_edit = QLineEdit(sw.toggle_hotkey)
        self.ptt_hotkey_edit = QLineEdit(sw.ptt_hotkey)
        self.ptt_hotkey_edit.setPlaceholderText(
            "Es. pause, scroll_lock, f12, <ctrl>+<space> (parla finché tieni premuto)"
        )
        self.panic_hotkey_edit = QLineEdit(cfg.panic.hotkey)
        self.auto_sleep_spin = QDoubleSpinBox()
        self.auto_sleep_spin.setRange(0.0, 300.0)
        self.auto_sleep_spin.setSingleStep(1.0)
        self.auto_sleep_spin.setDecimals(1)
        self.auto_sleep_spin.setSuffix(" s")
        self.auto_sleep_spin.setSpecialValueText("Disattivato")
        self.auto_sleep_spin.setValue(float(getattr(sw, "auto_sleep_after_sec", 0.0)))
        self.wake_emoji_edit = QLineEdit(sw.wake_emoji)
        self.sleep_emoji_edit = QLineEdit(sw.sleep_emoji)

        sw_row = self._make_hotkey_row(
            self.sw_hotkey_edit,
            "Sleep / Wake Mode",
            lambda: {
                "Push-to-Talk": self.ptt_hotkey_edit.text(),
                "PANIC / EMERGENCY": self.panic_hotkey_edit.text(),
            },
        )
        ptt_row = self._make_hotkey_row(
            self.ptt_hotkey_edit,
            "Push-to-Talk (Microfono)",
            lambda: {
                "Sleep / Wake Mode": self.sw_hotkey_edit.text(),
                "PANIC / EMERGENCY": self.panic_hotkey_edit.text(),
            },
        )

        sw_form.addRow("Parole chiave Sleep:", self.sleep_kw_edit)
        sw_form.addRow("Campioni Sleep (🔴):", self.sleep_sample_rec)
        sw_form.addRow("Parole chiave Wake:", self.wake_kw_edit)
        sw_form.addRow("Campioni Wake (🔴):", self.wake_sample_rec)
        sw_form.addRow("Hotkey globale Sleep/Wake:", sw_row)
        sw_form.addRow(
            "Hotkey Push-to-Talk (tieni premuto):",
            ptt_row,
        )
        sw_form.addRow(
            "Auto-ritorno in Sleep dopo:",
            self.auto_sleep_spin,
        )
        sw_form.addRow("Emoji Wake Mode:", self.wake_emoji_edit)
        sw_form.addRow("Emoji Sleep Mode:", self.sleep_emoji_edit)
        layout.addWidget(sw_box)

        p_box = QGroupBox("Panic / Emergency Globale")
        p_form = QFormLayout(p_box)
        p = cfg.panic
        self.panic_kw_edit = QLineEdit(_join_csv(p.voice_keywords))
        self.panic_sample_rec = SampleRecorderWidget(
            self.controller,
            lambda: "panic",
            initial_samples=p.voice_samples,
            compact=True,
            parent=self,
        )
        self.panic_no_prefix_chk = QCheckBox(
            "Attiva Panic vocale anche senza prefisso (consigliato)"
        )
        self.panic_no_prefix_chk.setChecked(p.allow_without_prefix)
        self.panic_sleep_chk = QCheckBox(
            "Entra in Sleep Mode (👋) dopo il reset di Panic"
        )
        self.panic_sleep_chk.setChecked(p.enter_sleep_mode)
        self.panic_xr18_chk = QCheckBox("Panic: Invia Mute Master LR OSC (se configurato)")
        self.panic_xr18_chk.setChecked(cfg.xr18.panic_mute_lr)
        self.panic_qlc_chk = QCheckBox("Panic: Invia Blackout Generale QLC+")
        self.panic_qlc_chk.setChecked(cfg.qlc.panic_blackout)

        panic_row = self._make_hotkey_row(
            self.panic_hotkey_edit,
            "PANIC / EMERGENCY",
            lambda: {
                "Sleep / Wake Mode": self.sw_hotkey_edit.text(),
                "Push-to-Talk": self.ptt_hotkey_edit.text(),
            },
        )
        p_form.addRow("Hotkey globale Panic:", panic_row)
        p_form.addRow("Comandi vocali Panic:", self.panic_kw_edit)
        p_form.addRow("Campioni Panic (🔴):", self.panic_sample_rec)
        p_form.addRow(self.panic_no_prefix_chk)
        p_form.addRow(self.panic_sleep_chk)
        p_form.addRow(self.panic_xr18_chk)
        p_form.addRow(self.panic_qlc_chk)
        layout.addWidget(p_box)
        layout.addStretch(1)

        self._add_scrollable_tab(w, "Sleep / Wake & Panic")

    # ------------------------------------------------------------------ Tab 3
    def _build_audio_tab(self, cfg: AppConfig) -> None:
        w = QWidget()
        form = QFormLayout(w)
        au = cfg.audio

        self.mic_combo = QComboBox()
        self.mic_combo.addItem("(Default di Sistema)", None)
        for dev in list_input_devices():
            self.mic_combo.addItem(dev.display_label, (dev.index, dev.name))
            if au.input_device_name and dev.name.lower() == au.input_device_name.lower():
                self.mic_combo.setCurrentIndex(self.mic_combo.count() - 1)
            elif au.input_device_index == dev.index and self.mic_combo.currentIndex() == 0:
                self.mic_combo.setCurrentIndex(self.mic_combo.count() - 1)
        form.addRow("Periferica Microfonica:", self.mic_combo)

        self.sr_spin = QSpinBox()
        self.sr_spin.setRange(8000, 48000)
        self.sr_spin.setValue(au.sample_rate)
        form.addRow("Sample Rate STT (Hz):", self.sr_spin)

        self.hpf_chk = QCheckBox("Filtro Passa-Alto (HPF) anti-rimbombo monitor di palco")
        self.hpf_chk.setChecked(au.highpass_enabled)
        form.addRow(self.hpf_chk)

        self.hpf_cutoff_spin = QDoubleSpinBox()
        self.hpf_cutoff_spin.setRange(20.0, 500.0)
        self.hpf_cutoff_spin.setValue(au.highpass_cutoff_hz)
        form.addRow("Frequenza taglio HPF (Hz):", self.hpf_cutoff_spin)

        self.gate_spin = QDoubleSpinBox()
        self.gate_spin.setRange(-85.0, -5.0)
        self.gate_spin.setValue(au.noise_gate_db)
        form.addRow("Soglia Noise Gate (dBFS):", self.gate_spin)

        self.hangover_spin = QSpinBox()
        self.hangover_spin.setRange(100, 2000)
        self.hangover_spin.setValue(au.vad_hangover_ms)
        form.addRow("Hold / Hangover VAD (ms):", self.hangover_spin)

        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(0.2, 5.0)
        self.gain_spin.setSingleStep(0.1)
        self.gain_spin.setValue(au.input_gain)
        form.addRow("Guadagno Digitale (x):", self.gain_spin)

        self._add_scrollable_tab(w, "Audio & Anti-Feedback")

    # ------------------------------------------------------------------ Tab 4
    def _build_stt_tab(self, cfg: AppConfig) -> None:
        w = QWidget()
        form = QFormLayout(w)
        stt = cfg.stt

        self.stt_engine_combo = QComboBox()
        self.stt_engine_combo.addItems(
            ["samples_hybrid", "samples_only", "vosk", "faster_whisper"]
        )
        self.stt_engine_combo.setCurrentText(stt.engine)
        form.addRow("Motore Riconoscimento:", self.stt_engine_combo)

        hint_lbl = QLabel(
            "• samples_hybrid (consigliato): confronta prima i campioni audio .wav "
            "(dialetto/inglese/voci custom, <30 ms); se nessun campione corrisponde, "
            "usa il fallback testuale per comandi variabili (es. 'apri {nome}').\n"
            "• samples_only: solo campioni audio registrati (velocità massima)."
        )
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet("color: #9fb3d9; font-size: 11px;")
        form.addRow(hint_lbl)

        self.sample_thresh_spin = QSpinBox()
        self.sample_thresh_spin.setRange(50, 95)
        self.sample_thresh_spin.setSuffix(" %")
        self.sample_thresh_spin.setValue(
            max(50, min(95, int(round(stt.sample_match_threshold * 100))))
        )
        form.addRow("Soglia Match Campioni:", self.sample_thresh_spin)

        self.fallback_combo = QComboBox()
        self.fallback_combo.addItems(["vosk", "faster_whisper", "none"])
        self.fallback_combo.setCurrentText(stt.hybrid_fallback_engine or "vosk")
        form.addRow("Fallback Ibrido:", self.fallback_combo)

        samples_dir_path = self.controller.stt.samples_dir or get_samples_dir()
        samples_count = self.controller.stt.sample_library.count
        samples_row = QHBoxLayout()
        self.samples_path_edit = QLineEdit(str(samples_dir_path))
        self.samples_path_edit.setReadOnly(True)
        open_samples_btn = QPushButton("📁 Apri")
        open_samples_btn.clicked.connect(
            lambda _=False, p=samples_dir_path: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(p))
            )
        )
        samples_row.addWidget(self.samples_path_edit)
        samples_row.addWidget(open_samples_btn)
        form.addRow(f"Cartella Campioni ({samples_count}):", samples_row)

        discovered = discover_local_models()
        self.discovered_label = QLabel(
            f"Modelli rilevati -> Vosk: {len(discovered['vosk'])} | Whisper: {len(discovered['faster_whisper'])}"
        )
        form.addRow(self.discovered_label)

        vosk_row = QHBoxLayout()
        self.vosk_path_edit = QLineEdit(stt.vosk_model_path)
        self.vosk_path_edit.textChanged.connect(self._update_vosk_status_label)
        vosk_btn = QPushButton("Sfoglia...")
        vosk_btn.clicked.connect(self._browse_vosk_folder)
        vosk_dl_btn = QPushButton("⬇️ Scarica IT")
        vosk_dl_btn.setToolTip("Scarica Modello Vosk Italiano (~48 MB)")
        vosk_dl_btn.clicked.connect(self._download_vosk_it_model)
        vosk_row.addWidget(self.vosk_path_edit, stretch=1)
        vosk_row.addWidget(vosk_btn)
        vosk_row.addWidget(vosk_dl_btn)
        form.addRow("Modello locale Vosk:", vosk_row)

        self.vosk_valid_label = QLabel()
        self.vosk_valid_label.setWordWrap(True)
        form.addRow("Stato Vosk:", self.vosk_valid_label)
        self._update_vosk_status_label()

        self.vosk_partial_chk = QCheckBox(
            "Trigger istantaneo su risultati parziali (Wake/Sleep/Panic)"
        )
        self.vosk_partial_chk.setChecked(stt.vosk_use_partial_triggers)
        form.addRow(self.vosk_partial_chk)

        wh_row = QHBoxLayout()
        self.whisper_model_edit = QLineEdit(stt.whisper_model_path_or_size)
        self.whisper_model_edit.textChanged.connect(self._update_whisper_status_label)
        wh_btn = QPushButton("Sfoglia...")
        wh_btn.clicked.connect(self._browse_whisper_folder)
        self.whisper_dl_size_combo = QComboBox()
        self.whisper_dl_size_combo.addItem("base (~145 MB)", "base")
        self.whisper_dl_size_combo.addItem("small (~465 MB)", "small")
        self.whisper_dl_btn = QPushButton("⬇️ Scarica")
        self.whisper_dl_btn.clicked.connect(self._download_whisper_model)
        wh_row.addWidget(self.whisper_model_edit, stretch=1)
        wh_row.addWidget(wh_btn)
        wh_row.addWidget(self.whisper_dl_size_combo)
        wh_row.addWidget(self.whisper_dl_btn)
        form.addRow("Modello Faster-Whisper:", wh_row)

        self.whisper_valid_label = QLabel()
        self.whisper_valid_label.setWordWrap(True)
        form.addRow("Stato Whisper:", self.whisper_valid_label)
        self._update_whisper_status_label()

        self.whisper_compute_combo = QComboBox()
        self.whisper_compute_combo.addItems(["int8", "float32", "float16"])
        self.whisper_compute_combo.setCurrentText(stt.whisper_compute_type)
        form.addRow("Whisper Compute Type:", self.whisper_compute_combo)

        self.whisper_beam_spin = QSpinBox()
        self.whisper_beam_spin.setRange(1, 5)
        self.whisper_beam_spin.setValue(stt.whisper_beam_size)
        form.addRow("Whisper Beam Size:", self.whisper_beam_spin)

        self._add_scrollable_tab(w, "Riconoscimento & Campioni")

    def _browse_vosk_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Seleziona cartella modello Vosk")
        if d:
            self.vosk_path_edit.setText(d)

    def _update_vosk_status_label(self) -> None:
        raw = self.vosk_path_edit.text().strip()
        if not raw:
            self.vosk_valid_label.setText("⚠️ Nessuna cartella selezionata (userà eventuale modello in models/).")
            self.vosk_valid_label.setStyleSheet("color: #f39c12;")
            return
        p = Path(raw)
        if is_valid_vosk_model_dir(p):
            self.vosk_valid_label.setText(f"✅ Modello Vosk valido pronto offline ({p.name})")
            self.vosk_valid_label.setStyleSheet("color: #2ecc71;")
        else:
            self.vosk_valid_label.setText(
                f"❌ '{p.name}' non contiene un modello Vosk valido (manca am/final.mdl o conf/mfcc.conf)."
            )
            self.vosk_valid_label.setStyleSheet("color: #ff6b6b;")

    def _download_vosk_it_model(self) -> None:
        import urllib.request
        import zipfile

        base_models = (
            get_app_base_dir() / "models"
            if is_portable_mode()
            else get_default_config_dir() / "models"
        )
        base_models.mkdir(parents=True, exist_ok=True)
        target_dir = base_models / "vosk-model-small-it-0.22"
        if is_valid_vosk_model_dir(target_dir):
            self.vosk_path_edit.setText(str(target_dir))
            QMessageBox.information(
                self, "Modello già presente", f"Modello trovato in:\n{target_dir}"
            )
            return

        url = "https://alphacephei.com/vosk/models/vosk-model-small-it-0.22.zip"
        zip_path = base_models / "vosk-model-small-it-0.22.zip"
        self.vosk_valid_label.setText("⏳ Scaricamento modello Vosk italiano in corso (~48 MB)...")
        self.vosk_valid_label.setStyleSheet("color: #60a5fa;")
        QApplication.processEvents()
        try:
            urllib.request.urlretrieve(url, zip_path)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(base_models)
            zip_path.unlink(missing_ok=True)
            self.vosk_path_edit.setText(str(target_dir))
            QMessageBox.information(
                self,
                "Modello Vosk installato",
                f"Modello offline pronto in:\n{target_dir}\nPremi '💾 Salva Impostazioni' per applicarlo.",
            )
        except Exception as exc:
            zip_path.unlink(missing_ok=True)
            self._update_vosk_status_label()
            QMessageBox.warning(
                self,
                "Errore download modello",
                f"Impossibile scaricare il modello ({exc}).\n"
                "Puoi scaricarlo manualmente e copiarlo nella cartella 'models/'.",
            )

    def _browse_whisper_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Seleziona cartella modello Faster-Whisper CTranslate2"
        )
        if d:
            self.whisper_model_edit.setText(d)

    def _refresh_discovered_models_label(self) -> None:
        discovered = discover_local_models()
        self.discovered_label.setText(
            f"Modelli rilevati -> Vosk: {len(discovered['vosk'])} | Whisper: {len(discovered['faster_whisper'])}"
        )

    def _update_whisper_status_label(self) -> None:
        raw = self.whisper_model_edit.text().strip()
        found = discover_local_models().get("faster_whisper", [])
        if raw:
            p = Path(raw)
            if is_valid_whisper_model_dir(p):
                self.whisper_valid_label.setText(
                    f"✅ Modello Whisper valido pronto offline ({p.name})"
                )
                self.whisper_valid_label.setStyleSheet("color: #2ecc71;")
                return
            looks_like_path = any(sep in raw for sep in ("/", "\\", ":")) or raw.startswith(".")
            if p.exists() or looks_like_path:
                hint = f" — fallback locale disponibile: {found[0].name}" if found else ""
                self.whisper_valid_label.setText(
                    f"❌ '{p.name or raw}' non contiene un modello Whisper valido (mancano model.bin o config.json){hint}."
                )
                self.whisper_valid_label.setStyleSheet("color: #ff6b6b;")
                return

        if found:
            wanted = raw.lower()
            exact = [
                f
                for f in found
                if wanted and (f.name.lower() == wanted or f.name.lower().endswith(f"-{wanted}"))
            ]
            chosen = exact[0] if exact else found[0]
            self.whisper_valid_label.setText(
                f"✅ Userà modello Whisper rilevato localmente ({chosen.name})"
            )
            self.whisper_valid_label.setStyleSheet("color: #2ecc71;")
            return

        self.whisper_valid_label.setText(
            f"⚠️ Nessun modello Whisper locale rilevato per '{raw or 'base'}'. Premi '⬇️ Scarica' per usarlo offline."
        )
        self.whisper_valid_label.setStyleSheet("color: #f39c12;")

    def _download_whisper_model(self) -> None:
        size = str(self.whisper_dl_size_combo.currentData() or "base")
        base_models = (
            get_app_base_dir() / "models"
            if is_portable_mode()
            else get_default_config_dir() / "models"
        )
        base_models.mkdir(parents=True, exist_ok=True)
        target_dir = base_models / f"faster-whisper-{size}"

        if is_valid_whisper_model_dir(target_dir):
            self.whisper_model_edit.setText(str(target_dir))
            self._refresh_discovered_models_label()
            self._update_whisper_status_label()
            QMessageBox.information(
                self, "Modello già presente", f"Modello Whisper trovato in:\n{target_dir}"
            )
            return

        size_hint = "~145 MB" if size == "base" else "~465 MB"
        self.whisper_valid_label.setText(
            f"⏳ Scaricamento modello Faster-Whisper '{size}' ({size_hint}) in corso..."
        )
        self.whisper_valid_label.setStyleSheet("color: #60a5fa;")
        self.whisper_dl_btn.setEnabled(False)
        self.whisper_dl_size_combo.setEnabled(False)

        err_box: list[Exception] = []

        def _worker() -> None:
            try:
                os.environ.pop("HF_HUB_OFFLINE", None)
                from faster_whisper import download_model

                download_model(size, output_dir=str(target_dir), local_files_only=False)
            except Exception as exc:
                err_box.append(exc)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        try:
            while t.is_alive():
                QApplication.processEvents()
                t.join(timeout=0.05)
        finally:
            self.whisper_dl_btn.setEnabled(True)
            self.whisper_dl_size_combo.setEnabled(True)

        if err_box or not is_valid_whisper_model_dir(target_dir):
            exc = err_box[0] if err_box else RuntimeError("File modello incompleti")
            self._update_whisper_status_label()
            QMessageBox.warning(
                self,
                "Errore download modello Whisper",
                f"Impossibile scaricare Faster-Whisper '{size}' ({exc}).\n"
                "Puoi scaricarlo manualmente e copiarlo nella cartella 'models/'.",
            )
            return

        self.whisper_model_edit.setText(str(target_dir))
        if self.whisper_compute_combo.currentText() == "float32":
            self.whisper_compute_combo.setCurrentText("int8")
        self._refresh_discovered_models_label()
        self._update_whisper_status_label()
        QMessageBox.information(
            self,
            "Modello Whisper installato",
            f"Modello offline '{size}' pronto in:\n{target_dir}\n\n"
            "Consigliato su CPU: Compute Type = int8.\n"
            "Ricorda di selezionare 'faster_whisper' in Fallback Ibrido e premere '💾 Salva Impostazioni'.",
        )

    def sync_audio_controls(
        self,
        input_gain: float,
        noise_gate_db: float,
        device_index: int | None = None,
        device_name: str = "",
    ) -> None:
        """Keep quick audio controls in sync with MainWindow top sliders/combo."""
        for widget, val in ((self.gain_spin, input_gain), (self.gate_spin, noise_gate_db)):
            widget.blockSignals(True)
            widget.setValue(float(val))
            widget.blockSignals(False)

        self.mic_combo.blockSignals(True)
        self.mic_combo.setCurrentIndex(0)
        for idx in range(1, self.mic_combo.count()):
            data = self.mic_combo.itemData(idx)
            if isinstance(data, tuple) and len(data) == 2:
                if device_name and str(data[1]).lower() == device_name.lower():
                    self.mic_combo.setCurrentIndex(idx)
                    break
                if device_index is not None and int(data[0]) == device_index:
                    self.mic_combo.setCurrentIndex(idx)
        self.mic_combo.blockSignals(False)

    def apply_to_config(self, d: AppConfig) -> AppConfig:
        """Write system tab fields onto AppConfig without touching d.programs."""
        d.general.language = self.lang_combo.currentText()
        d.general.minimize_on_close = self.min_on_close_chk.isChecked()
        d.general.start_minimized_to_tray = self.start_min_chk.isChecked()
        d.general.autostart_at_os_boot = self.autostart_chk.isChecked()
        d.general.autostart_in_background = self.autostart_bg_chk.isChecked()

        d.stage_launcher.launch_apps_on_art_director_start = self.sl_auto_start_chk.isChecked()
        d.stage_launcher.initial_startup_delay_sec = self.sl_delay_spin.value()
        d.stage_launcher.voice_launch_all_triggers = _split_csv(self.sl_all_triggers_edit.text())
        d.stage_launcher.launch_all_samples = list(self.launch_all_sample_rec.samples)

        d.popup_handler.enabled = self.pop_enabled_chk.isChecked()
        d.popup_handler.strategy = self.pop_strategy_combo.currentText()
        d.popup_handler.voice_triggers = _split_csv(self.pop_triggers_edit.text())
        d.popup_handler.voice_samples = list(self.popup_sample_rec.samples)
        d.popup_handler.protect_main_windows = self.pop_protect_chk.isChecked()

        d.sleep_wake.start_in_sleep_mode = self.start_sleep_chk.isChecked()
        d.sleep_wake.mute_mic_in_sleep = self.mute_in_sleep_chk.isChecked()
        d.sleep_wake.sleep_keywords = _split_csv(self.sleep_kw_edit.text())
        d.sleep_wake.sleep_samples = list(self.sleep_sample_rec.samples)
        d.sleep_wake.wake_keywords = _split_csv(self.wake_kw_edit.text())
        d.sleep_wake.wake_samples = list(self.wake_sample_rec.samples)
        d.sleep_wake.toggle_hotkey = self.sw_hotkey_edit.text().strip()
        d.sleep_wake.ptt_hotkey = self.ptt_hotkey_edit.text().strip()
        d.sleep_wake.auto_sleep_after_sec = float(self.auto_sleep_spin.value())
        d.sleep_wake.wake_emoji = self.wake_emoji_edit.text().strip() or "👍"
        d.sleep_wake.sleep_emoji = self.sleep_emoji_edit.text().strip() or "👋"

        d.panic.hotkey = self.panic_hotkey_edit.text().strip()
        d.panic.voice_keywords = _split_csv(self.panic_kw_edit.text())
        d.panic.voice_samples = list(self.panic_sample_rec.samples)
        d.panic.allow_without_prefix = self.panic_no_prefix_chk.isChecked()
        d.panic.enter_sleep_mode = self.panic_sleep_chk.isChecked()
        d.xr18.panic_mute_lr = self.panic_xr18_chk.isChecked()
        d.qlc.panic_blackout = self.panic_qlc_chk.isChecked()

        mic_data = self.mic_combo.currentData()
        if isinstance(mic_data, tuple) and len(mic_data) == 2:
            d.audio.input_device_index = int(mic_data[0])
            d.audio.input_device_name = str(mic_data[1])
        else:
            d.audio.input_device_index = None
            d.audio.input_device_name = ""
        d.audio.sample_rate = self.sr_spin.value()
        d.audio.highpass_enabled = self.hpf_chk.isChecked()
        d.audio.highpass_cutoff_hz = self.hpf_cutoff_spin.value()
        d.audio.noise_gate_db = self.gate_spin.value()
        d.audio.vad_hangover_ms = self.hangover_spin.value()
        d.audio.input_gain = self.gain_spin.value()

        d.stt.engine = self.stt_engine_combo.currentText()
        d.stt.sample_match_threshold = self.sample_thresh_spin.value() / 100.0
        d.stt.hybrid_fallback_engine = self.fallback_combo.currentText()
        d.stt.vosk_model_path = self.vosk_path_edit.text().strip()
        d.stt.vosk_use_partial_triggers = self.vosk_partial_chk.isChecked()
        d.stt.whisper_model_path_or_size = self.whisper_model_edit.text().strip()
        d.stt.whisper_compute_type = self.whisper_compute_combo.currentText()
        d.stt.whisper_beam_size = self.whisper_beam_spin.value()
        return d

    def load_from_config(self, d: AppConfig) -> None:
        """Reload all 4 system tabs from an AppConfig."""
        g = d.general
        sl = d.stage_launcher
        ph = d.popup_handler
        sw = d.sleep_wake
        p = d.panic
        au = d.audio
        stt = d.stt

        self.lang_combo.setCurrentText(g.language)
        self.min_on_close_chk.setChecked(g.minimize_on_close)
        self.start_min_chk.setChecked(g.start_minimized_to_tray)
        self.autostart_chk.setChecked(g.autostart_at_os_boot)
        self.autostart_bg_chk.setChecked(g.autostart_in_background)
        self._refresh_active_profile_label(d)

        self.sl_auto_start_chk.setChecked(sl.launch_apps_on_art_director_start)
        self.sl_delay_spin.setValue(sl.initial_startup_delay_sec)
        self.sl_all_triggers_edit.setText(_join_csv(sl.voice_launch_all_triggers))
        self.launch_all_sample_rec.set_samples(sl.launch_all_samples)

        self.pop_enabled_chk.setChecked(ph.enabled)
        self.pop_strategy_combo.setCurrentText(ph.strategy)
        self.pop_triggers_edit.setText(_join_csv(ph.voice_triggers))
        self.popup_sample_rec.set_samples(ph.voice_samples)
        self.pop_protect_chk.setChecked(ph.protect_main_windows)

        self.start_sleep_chk.setChecked(sw.start_in_sleep_mode)
        self.mute_in_sleep_chk.setChecked(sw.mute_mic_in_sleep)
        self.sleep_kw_edit.setText(_join_csv(sw.sleep_keywords))
        self.sleep_sample_rec.set_samples(sw.sleep_samples)
        self.wake_kw_edit.setText(_join_csv(sw.wake_keywords))
        self.wake_sample_rec.set_samples(sw.wake_samples)
        self.sw_hotkey_edit.setText(sw.toggle_hotkey)
        self.ptt_hotkey_edit.setText(getattr(sw, "ptt_hotkey", ""))
        self.auto_sleep_spin.setValue(float(getattr(sw, "auto_sleep_after_sec", 0.0)))
        self.wake_emoji_edit.setText(sw.wake_emoji)
        self.sleep_emoji_edit.setText(sw.sleep_emoji)

        self.panic_hotkey_edit.setText(p.hotkey)
        self.panic_kw_edit.setText(_join_csv(p.voice_keywords))
        self.panic_sample_rec.set_samples(p.voice_samples)
        self.panic_no_prefix_chk.setChecked(p.allow_without_prefix)
        self.panic_sleep_chk.setChecked(p.enter_sleep_mode)
        self.panic_xr18_chk.setChecked(d.xr18.panic_mute_lr)
        self.panic_qlc_chk.setChecked(d.qlc.panic_blackout)

        self.mic_combo.clear()
        self.mic_combo.addItem("(Default di Sistema)", None)
        for dev in list_input_devices():
            self.mic_combo.addItem(dev.display_label, (dev.index, dev.name))
        self.sync_audio_controls(
            au.input_gain,
            au.noise_gate_db,
            au.input_device_index,
            au.input_device_name,
        )
        self.sr_spin.setValue(au.sample_rate)
        self.hpf_chk.setChecked(au.highpass_enabled)
        self.hpf_cutoff_spin.setValue(au.highpass_cutoff_hz)
        self.hangover_spin.setValue(au.vad_hangover_ms)

        self.stt_engine_combo.setCurrentText(stt.engine)
        self.sample_thresh_spin.setValue(
            max(50, min(95, int(round(stt.sample_match_threshold * 100))))
        )
        self.fallback_combo.setCurrentText(stt.hybrid_fallback_engine or "vosk")
        self.vosk_path_edit.setText(stt.vosk_model_path)
        self.vosk_partial_chk.setChecked(stt.vosk_use_partial_triggers)
        self.whisper_model_edit.setText(stt.whisper_model_path_or_size)
        self.whisper_compute_combo.setCurrentText(stt.whisper_compute_type)
        self.whisper_beam_spin.setValue(stt.whisper_beam_size)
        self._update_vosk_status_label()
        self._update_whisper_status_label()

    def _on_save_clicked(self) -> None:
        updated = copy.deepcopy(self.controller.config)
        self.apply_to_config(updated)
        self.controller.config_manager.save(updated)
        if hasattr(self, "status_hint_lbl"):
            self.status_hint_lbl.setText("✅ Impostazioni di sistema salvate e applicate.")
            self.status_hint_lbl.setStyleSheet("color: #4ade80; font-size: 11px;")
        if self._on_settings_saved_cb is not None:
            self._on_settings_saved_cb()

    def cleanup(self) -> None:
        for rec in (
            getattr(self, "launch_all_sample_rec", None),
            getattr(self, "popup_sample_rec", None),
            getattr(self, "sleep_sample_rec", None),
            getattr(self, "wake_sample_rec", None),
            getattr(self, "panic_sample_rec", None),
        ):
            if rec is not None:
                rec.cleanup()


class SettingsDialog(SafeModalDialog):
    """App / Settings layer dedicated exclusively to managed stage applications."""

    def __init__(
        self, controller: ArtDirectorController, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._draft: AppConfig = copy.deepcopy(controller.config)
        self._loaded_from_file: bool = False
        self._program_tabs: list[ProgramTabWidget] = []
        self._tab_scrolls: dict[int, QScrollArea] = {}

        self.setWindowTitle("Art Director — App / Settings (Applicazioni da Pilotare)")
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(
                max(880, min(1160, int(avail.width() * 0.92))),
                max(540, min(700, int(avail.height() * 0.84))),
            )
        else:
            self.resize(1120, 680)

        root = QVBoxLayout(self)

        # Top action bar with green "+ Aggiungi Programma"
        top_bar = QHBoxLayout()
        info_lbl = QLabel(
            "Secondo layer dedicato esclusivamente alle Applicazioni da pilotare (es. X-AIR Edit, Sonar, QLC+, VirtualDJ)."
        )
        info_lbl.setStyleSheet("color: #9fb3d9;")
        self.add_prog_btn = QPushButton("+ Aggiungi Programma (Passo 1-2-3)")
        self.add_prog_btn.setStyleSheet(
            "QPushButton { background-color: #15803d; color: white; font-weight: 700; padding: 7px 14px; }"
            "QPushButton:hover { background-color: #16a34a; }"
        )
        self.add_prog_btn.clicked.connect(self._on_add_program)
        top_bar.addWidget(info_lbl, stretch=1)
        top_bar.addWidget(self.add_prog_btn)
        root.addLayout(top_bar)

        self.content_stack = QStackedWidget(self)
        root.addWidget(self.content_stack, stretch=1)

        # Page 0: friendly empty state when no app is configured yet
        empty_page = QWidget(self)
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.addStretch(1)
        empty_lbl = QLabel(
            "<b>Nessuna applicazione ancora configurata.</b><br><br>"
            "Premi il pulsante verde qui sotto per selezionare un programma installato, "
            "registrare il comando vocale di apertura e fare Picking o aggiungere azioni OSC / MIDI / Art-Net."
        )
        empty_lbl.setWordWrap(True)
        empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lbl.setStyleSheet("color: #cbd5e1; font-size: 14px;")
        empty_add_btn = QPushButton("➕ Aggiungi la tua prima Applicazione (Passo 1-2-3)")
        empty_add_btn.setMinimumHeight(44)
        empty_add_btn.setStyleSheet(
            "QPushButton { background-color: #15803d; color: white; font-size: 14px; font-weight: 800; padding: 8px 20px; }"
            "QPushButton:hover { background-color: #16a34a; }"
        )
        empty_add_btn.clicked.connect(self._on_add_program)
        btn_wrap = QHBoxLayout()
        btn_wrap.addStretch(1)
        btn_wrap.addWidget(empty_add_btn)
        btn_wrap.addStretch(1)
        empty_layout.addWidget(empty_lbl)
        empty_layout.addSpacing(14)
        empty_layout.addLayout(btn_wrap)
        empty_layout.addStretch(1)
        self.content_stack.addWidget(empty_page)

        # Page 1: dynamic ProgramProfile tabs only
        self.tabs = QTabWidget(self)
        self.content_stack.addWidget(self.tabs)

        for prog in self._draft.programs:
            self._append_program_tab(prog)
        self._update_stack_visibility()

        bottom = QHBoxLayout()
        self.load_cfg_btn = QPushButton("📂 Carica Config...")
        self.load_cfg_btn.setMinimumHeight(36)
        self.load_cfg_btn.clicked.connect(self._on_load_config)
        self.save_as_cfg_btn = QPushButton("💾 Salva Config Come...")
        self.save_as_cfg_btn.setMinimumHeight(36)
        self.save_as_cfg_btn.clicked.connect(self._on_save_config_as)
        bottom.addWidget(self.load_cfg_btn)
        bottom.addWidget(self.save_as_cfg_btn)
        bottom.addStretch(1)
        self.cancel_btn = QPushButton("Annulla")
        self.cancel_btn.setMinimumHeight(38)
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn = QPushButton("💾 Salva App")
        self.save_btn.setMinimumHeight(38)
        self.save_btn.setMinimumWidth(140)
        self.save_btn.setStyleSheet(
            "QPushButton { background-color: #15803d; color: white; font-size: 14px; font-weight: 800; }"
            "QPushButton:hover { background-color: #16a34a; }"
        )
        self.save_btn.clicked.connect(self._on_save)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.save_btn)
        root.addLayout(bottom)

    @property
    def edited_config(self) -> AppConfig:
        return self._draft

    @property
    def loaded_from_file(self) -> bool:
        return self._loaded_from_file

    def _add_scrollable_tab(self, widget: QWidget, label: str) -> QScrollArea:
        scroll = QScrollArea(self.tabs)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, label)
        self._tab_scrolls[id(widget)] = scroll
        return scroll

    def _update_stack_visibility(self) -> None:
        self.content_stack.setCurrentIndex(1 if self._program_tabs else 0)

    def _configs_dir(self) -> Path:
        return get_configs_dir(self.controller.config_manager.path.parent)

    def _samples_dir(self) -> Path:
        return self.controller.stt.samples_dir or get_samples_dir()

    # ------------------------------------------------------------------ Dynamic Program Tabs
    def _on_add_program(self) -> None:
        wiz = AddProgramWizardDialog(self.controller, parent=self)
        if wiz.exec() and wiz.created_profile is not None:
            prof = wiz.created_profile
            existing_ids = {p.id for p in self._draft.programs}
            base_id = prof.id
            n = 2
            while prof.id in existing_ids:
                prof.id = f"{base_id}_{n}"
                n += 1
            self._draft.programs.append(prof)
            tab_w = self._append_program_tab(prof)
            self._update_stack_visibility()
            self.tabs.setCurrentWidget(self._tab_scrolls.get(id(tab_w), tab_w))

    def _append_program_tab(self, profile: ProgramProfile) -> ProgramTabWidget:
        tab_w = ProgramTabWidget(self.controller, profile, parent=self)
        tab_w.remove_requested.connect(self._on_remove_program)
        self._program_tabs.append(tab_w)
        self._add_scrollable_tab(tab_w, profile.name)
        return tab_w

    def _on_remove_program(self, program_id: str) -> None:
        for idx, tab_w in enumerate(self._program_tabs):
            if tab_w.profile.id == program_id:
                tab_w.cleanup()
                scroll = self._tab_scrolls.pop(id(tab_w), tab_w)
                tab_idx = self.tabs.indexOf(scroll)
                if tab_idx >= 0:
                    self.tabs.removeTab(tab_idx)
                scroll.deleteLater()
                self._program_tabs.pop(idx)
                break
        self._draft.programs = [p for p in self._draft.programs if p.id != program_id]
        self._update_stack_visibility()

    def _cleanup_all_program_tabs(self) -> None:
        for tab_w in self._program_tabs:
            tab_w.cleanup()

    def reject(self) -> None:
        self._cleanup_all_program_tabs()
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cleanup_all_program_tabs()
        super().closeEvent(event)

    def _collect_draft_config(self) -> AppConfig:
        base = (
            copy.deepcopy(self._draft)
            if self._loaded_from_file
            else copy.deepcopy(self.controller.config)
        )
        base.programs = [tab_w.apply_to_profile() for tab_w in self._program_tabs]
        self._draft = base
        return self._draft

    def _apply_draft_to_tabs(self) -> None:
        for tab_w in list(self._program_tabs):
            tab_w.cleanup()
            scroll = self._tab_scrolls.pop(id(tab_w), tab_w)
            tab_idx = self.tabs.indexOf(scroll)
            if tab_idx >= 0:
                self.tabs.removeTab(tab_idx)
            scroll.deleteLater()
        self._program_tabs.clear()
        for prog in self._draft.programs:
            self._append_program_tab(prog)
        self._update_stack_visibility()

    def _on_save_config_as(self) -> None:
        draft = self._collect_draft_config()
        dlg = SaveConfigProfileDialog(
            config=draft,
            configs_dir=self._configs_dir(),
            samples_dir=self._samples_dir(),
            parent=self,
        )
        if dlg.exec() and dlg.saved_path is not None:
            current_ids = {p.id for p in draft.programs}
            if dlg.selected_program_ids == current_ids or not current_ids:
                self._draft.general.active_profile_name = dlg.profile_name
            QMessageBox.information(
                self,
                "Configurazione salvata",
                f"Setup salvato in:\n{dlg.saved_path}\n"
                f"Programmi inclusi: {len(dlg.selected_program_ids)} · Campioni: {dlg.exported_samples}",
            )

    def _on_load_config(self) -> None:
        current = self._collect_draft_config()
        dlg = LoadConfigProfileDialog(
            current_config=current,
            configs_dir=self._configs_dir(),
            samples_dir=self._samples_dir(),
            parent=self,
        )
        if dlg.exec() and dlg.loaded_config is not None:
            self._draft = copy.deepcopy(dlg.loaded_config)
            self._loaded_from_file = True
            self._apply_draft_to_tabs()
            extra = (
                f"\nCampioni .wav importati in 'campioni/': {dlg.extracted_samples}"
                if dlg.extracted_samples > 0
                else ""
            )
            QMessageBox.information(
                self,
                "Configurazione caricata",
                f"Setup '{dlg.loaded_profile_name}' caricato ({len(self._draft.programs)} programmi).{extra}\n\n"
                "Controlla le schede e premi '💾 Salva App' in basso a destra per applicarla.",
            )

    # ------------------------------------------------------------------ Save
    def _on_save(self) -> None:
        self._collect_draft_config()
        self._cleanup_all_program_tabs()
        self.accept()
