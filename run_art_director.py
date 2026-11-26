"""Entry point for Art Director GUI & System Tray Daemon."""

from __future__ import annotations

import argparse
import sys

from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from art_director.config import ConfigManager, get_resource_path
from art_director.core import ArtDirectorController
from art_director.os_layer import install_on_system, uninstall_from_system
from art_director.ui import MainWindow

_INSTANCE_KEY = "ArtDirector_SingleInstance_v1"


def _notify_running_instance(server_name: str) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if sock.waitForConnected(250):
        sock.write(b"SHOW")
        sock.waitForBytesWritten(250)
        sock.disconnectFromServer()
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Art Director - 100% Offline Cross-Platform Stage Voice Controller"
    )
    parser.add_argument(
        "--background",
        "--tray",
        action="store_true",
        dest="background",
        help="Avvia direttamente in background nella System Tray",
    )
    parser.add_argument(
        "--boot",
        action="store_true",
        help="Segnala che l'avvio è avvenuto al boot del sistema operativo",
    )
    parser.add_argument(
        "--portable",
        action="store_true",
        help="Salva configurazione nella stessa cartella dell'eseguibile (Pen Drive)",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Installa Art Director su questo PC (Desktop + Menu Start)",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Disinstalla Art Director da questo PC",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Percorso personalizzato per config.json",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Avvia senza aprire la periferica microfonica (diagnostica)",
    )
    args = parser.parse_args(argv)

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Art Director")
    qt_app.setQuitOnLastWindowClosed(False)

    icon_path = get_resource_path("assets/art_director.png")
    if icon_path.exists():
        qt_app.setWindowIcon(QIcon(str(icon_path)))

    if args.install:
        ok, msg = install_on_system(copy_models=True)
        if ok:
            QMessageBox.information(None, "Art Director — Installazione", msg)
            return 0
        QMessageBox.warning(None, "Art Director — Installazione", msg)
        return 1

    if args.uninstall:
        ans = QMessageBox.question(
            None,
            "Disinstalla Art Director",
            "Rimuovere Art Director, collegamenti e voci di avvio da questo PC?",
        )
        if ans == QMessageBox.StandardButton.Yes:
            _ok, msg = uninstall_from_system()
            QMessageBox.information(None, "Art Director — Disinstallazione", msg)
        return 0

    if not args.config and _notify_running_instance(_INSTANCE_KEY):
        return 0

    server = None
    if not args.config:
        QLocalServer.removeServer(_INSTANCE_KEY)
        server = QLocalServer(qt_app)
        server.listen(_INSTANCE_KEY)

    cfg_manager = ConfigManager(args.config)
    controller = ArtDirectorController(
        config_manager=cfg_manager,
        enable_audio=not args.no_audio,
        enable_hotkeys=True,
    )
    launched_at_boot = bool(args.background or args.boot)
    window = MainWindow(controller=controller, start_hidden=args.background)

    if server is not None:
        def _on_new_connection() -> None:
            conn = server.nextPendingConnection()
            if conn is not None:
                conn.waitForReadyRead(100)
                conn.close()
                conn.deleteLater()
            window.restore_from_tray()

        server.newConnection.connect(_on_new_connection)

    controller.start(launched_at_boot=launched_at_boot)

    try:
        return qt_app.exec()
    finally:
        if server is not None:
            server.close()
        controller.stop()
        window.deleteLater()


if __name__ == "__main__":
    raise SystemExit(main())
