"""Cross-platform System Tray daemon icon and context menu (loopMIDI-style)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from ..config.manager import (
    export_config_file,
    get_configs_dir,
    get_samples_dir,
    import_config_file,
    list_saved_configs,
    merge_loaded_config,
)
from ..core.controller import ArtDirectorController
from ..core.state import ListeningMode


def create_tray_icon(mode: ListeningMode) -> QIcon:
    """Render a crisp 64x64 dynamic badge icon for Windows/macOS/Linux tray."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if mode == ListeningMode.WAKE:
        bg = QColor("#1e8449")
        ring = QColor("#2ecc71")
    elif mode == ListeningMode.SLEEP:
        bg = QColor("#9a6700")
        ring = QColor("#f39c12")
    else:
        bg = QColor("#922b21")
        ring = QColor("#e74c3c")

    painter.setBrush(bg)
    painter.setPen(ring)
    painter.drawEllipse(3, 3, 58, 58)

    painter.setPen(QColor("#ffffff"))
    font = QFont("Segoe UI", 22, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "AD")
    painter.end()
    return QIcon(pixmap)


class ArtDirectorTray(QSystemTrayIcon):
    """Background system tray controller keeping Art Director alive when GUI is closed."""

    def __init__(
        self,
        controller: ArtDirectorController,
        on_show_window,
        on_quit_app,
        on_config_switched=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._on_show_window = on_show_window
        self._on_quit_app = on_quit_app
        self._on_config_switched = on_config_switched

        self._menu = QMenu()
        self._status_action = QAction("👍 Wake Mode (Attivo)", self._menu)
        self._status_action.setEnabled(False)

        self._show_action = QAction("Apri Configurazione (Art Director)", self._menu)
        self._show_action.triggered.connect(self._on_show_window)

        self._toggle_action = QAction("Passa a Sleep Mode (👋)", self._menu)
        self._toggle_action.triggered.connect(
            lambda: self.controller.toggle_sleep_wake(source="tray")
        )

        self._profiles_menu = self._menu.addMenu("📂 Carica Configurazione")
        self._profiles_menu.aboutToShow.connect(self._populate_profiles_menu)

        self._launch_apps_action = QAction("🚀 Avvia App di Palco", self._menu)
        self._launch_apps_action.triggered.connect(
            self.controller.launch_stage_apps_now
        )

        self._panic_action = QAction("🚨 PANIC / EMERGENCY", self._menu)
        self._panic_action.triggered.connect(
            lambda: self.controller.trigger_panic(source="tray")
        )

        self._quit_action = QAction("Esci da Art Director", self._menu)
        self._quit_action.triggered.connect(self._on_quit_app)

        self._menu.addAction(self._status_action)
        self._menu.addSeparator()
        self._menu.addAction(self._show_action)
        self._menu.addAction(self._toggle_action)
        self._menu.addMenu(self._profiles_menu)
        self._menu.addAction(self._launch_apps_action)
        self._menu.addAction(self._panic_action)
        self._menu.addSeparator()
        self._menu.addAction(self._quit_action)

        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)
        self.refresh_state()

    def _populate_profiles_menu(self) -> None:
        self._profiles_menu.clear()
        configs_dir = get_configs_dir(self.controller.config_manager.path.parent)
        presets = list_saved_configs(configs_dir)
        active = self.controller.config.general.active_profile_name.strip().lower()
        if not presets:
            empty_act = self._profiles_menu.addAction(
                "(Nessuna configurazione in configurazioni/)"
            )
            empty_act.setEnabled(False)
            return
        for info in presets:
            name = str(info["name"])
            prefix = "✓ " if active and name.lower() == active else ""
            progs = ", ".join(info["programs"]) or "Nessuna app"
            act = self._profiles_menu.addAction(f"{prefix}{name}  ({progs})")
            act.triggered.connect(
                lambda _checked=False, p=Path(info["path"]), n=name: self._switch_to_profile(p, n)
            )

    def _switch_to_profile(self, path: Path, profile_name: str) -> None:
        try:
            samples_dir = self.controller.stt.samples_dir or get_samples_dir()
            imported, _ = import_config_file(path, samples_dir=samples_dir)
            merged = merge_loaded_config(
                imported,
                self.controller.config,
                keep_audio_and_stt=True,
                profile_name=profile_name,
            )
            try:
                backup_path = self.controller.config_manager.path.with_name(
                    "config.backup_precedente.json"
                )
                export_config_file(self.controller.config, backup_path, samples_dir=samples_dir)
            except Exception:
                pass
            self.controller.config_manager.save(merged)
            self.refresh_state()
            if self._on_config_switched is not None:
                self._on_config_switched(profile_name)
            self.showMessage(
                "Configurazione caricata",
                f"{profile_name} ({len(merged.programs)} programmi)",
            )
        except Exception as exc:
            self.showMessage(
                "Errore caricamento",
                f"Impossibile caricare '{profile_name}': {exc}",
            )

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._on_show_window()

    def refresh_state(self) -> None:
        mode = self.controller.state.mode
        emoji = self.controller.state.emoji
        label = self.controller.state.label
        self.setIcon(create_tray_icon(mode))
        self.setToolTip(f"Art Director — {emoji} {label}")
        self._status_action.setText(f"{emoji} {label}")
        if mode == ListeningMode.WAKE:
            self._toggle_action.setText(
                f"Passa a Sleep Mode ({self.controller.config.sleep_wake.sleep_emoji})"
            )
        else:
            self._toggle_action.setText(
                f"Attiva Wake Mode ({self.controller.config.sleep_wake.wake_emoji})"
            )
