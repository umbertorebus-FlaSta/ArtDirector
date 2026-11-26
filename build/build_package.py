"""Build standalone portable & installable Art Director package for Pen Drive."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = PROJECT_ROOT / "build" / "art_director.spec"
DIST_DIR = PROJECT_ROOT / "dist"
WORK_DIR = PROJECT_ROOT / "build" / "pyinstaller_work"
PENDRIVE_DIR = PROJECT_ROOT / "ArtDirector_PenDrive"


def main() -> int:
    assets_ico = PROJECT_ROOT / "art_director" / "assets" / "art_director.ico"
    if not assets_ico.exists():
        subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "build" / "generate_icon.py")],
            check=True,
        )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            "--distpath",
            str(DIST_DIR),
            "--workpath",
            str(WORK_DIR),
            str(SPEC_PATH),
        ],
        check=True,
        cwd=str(PROJECT_ROOT),
    )

    # Preserve existing user data (config.json, campioni/*.wav) inside ArtDirector_PenDrive
    PENDRIVE_DIR.mkdir(parents=True, exist_ok=True)
    exe_locked = False

    if sys.platform == "win32":
        built_exe = DIST_DIR / "ArtDirector.exe"
        target_exe = PENDRIVE_DIR / "ArtDirector.exe"
        try:
            shutil.copy2(built_exe, target_exe)
        except PermissionError:
            exe_locked = True
            fallback_exe = PENDRIVE_DIR / "ArtDirector_NUOVO.exe"
            shutil.copy2(built_exe, fallback_exe)
            print(
                f"\n[ATTENZIONE] Impossibile sovrascrivere {target_exe} perche' "
                "ArtDirector.exe e' attualmente aperto in esecuzione (System Tray).\n"
                f"Il nuovo eseguibile e' stato salvato come: {fallback_exe}\n"
                "Chiudi Art Director dalla System Tray e rinomina ArtDirector_NUOVO.exe -> ArtDirector.exe."
            )
        (PENDRIVE_DIR / "Installa_ArtDirector.bat").write_text(
            '@echo off\r\n"%~dp0ArtDirector.exe" --install\r\n',
            encoding="utf-8",
        )
    elif sys.platform == "darwin":
        built_app = DIST_DIR / "ArtDirector.app"
        dst_app = PENDRIVE_DIR / "ArtDirector.app"
        if dst_app.exists():
            shutil.rmtree(dst_app)
        shutil.copytree(built_app, dst_app)
    else:
        built_bin = DIST_DIR / "ArtDirector"
        dst_bin = PENDRIVE_DIR / "ArtDirector"
        shutil.copy2(built_bin, dst_bin)
        dst_bin.chmod(0o755)

    (PENDRIVE_DIR / "portable.flag").write_text(
        "Rimuovi questo file se preferisci salvare config.json nel profilo utente del PC.\n",
        encoding="utf-8",
    )

    models_dir = PENDRIVE_DIR / "models"
    models_dir.mkdir(exist_ok=True)
    src_models = PROJECT_ROOT / "models"
    if src_models.exists() and src_models.is_dir():
        for item in src_models.iterdir():
            if item.is_dir():
                shutil.copytree(item, models_dir / item.name, dirs_exist_ok=True)
    (models_dir / "LEGGIMI_MODELLI.txt").write_text(
        "Inserisci qui dentro la cartella del modello vocale 100% offline "
        "(es. vosk-model-small-it-0.22 oppure una cartella Faster-Whisper).\n"
        "Art Director la rilevera' automaticamente all'avvio su qualsiasi PC!\n",
        encoding="utf-8",
    )

    campioni_dir = PENDRIVE_DIR / "campioni"
    campioni_dir.mkdir(exist_ok=True)
    (campioni_dir / "LEGGIMI_CAMPIONI.txt").write_text(
        "Cartella dei campioni audio vocali (.wav PCM 16 kHz) registrati da Art Director.\n"
        "Con 'portable.flag' attivo, i tuoi campioni restano qui sulla Pen Drive insieme\n"
        "a 'config.json' e ai modelli in 'models/', pronti su qualsiasi PC senza cloud.\n",
        encoding="utf-8",
    )

    configs_dir = PENDRIVE_DIR / "configurazioni"
    configs_dir.mkdir(exist_ok=True)
    (configs_dir / "LEGGIMI_CONFIGURAZIONI.txt").write_text(
        "Cartella dei profili e configurazioni salvate (.json / pacchetti .zip).\n"
        "Puoi salvare setup con solo 1, 2 o piu' applicazioni dalla finestra principale\n"
        "o dai Settings ('Salva Config...') e ricaricarli istantaneamente ('Carica Config...').\n",
        encoding="utf-8",
    )

    (PENDRIVE_DIR / "LEGGIMI.txt").write_text(
        "ART DIRECTOR - VERSIONE PORTATILE & INSTALLABILE\n"
        "================================================\n\n"
        "1. USO PORTATILE DA PEN DRIVE (senza installare nulla):\n"
        "   - Copia l'intera cartella 'ArtDirector_PenDrive' (o il solo ArtDirector.exe)\n"
        "     sulla tua Pen Drive.\n"
        "   - Fai doppio clic su ArtDirector.exe.\n"
        "   - Grazie al file 'portable.flag', configurazione (config.json), modelli\n"
        "     in 'models/' e campioni vocali in 'campioni/' restano sulla Pen Drive.\n\n"
        "2. INSTALLAZIONE SU UN PC (Desktop, Menu Start e Avvio Automatico):\n"
        "   - Fai doppio clic su 'Installa_ArtDirector.bat' oppure apri\n"
        "     ArtDirector.exe -> Settings -> Generale & Tray -> 'Installa su questo PC'.\n"
        "   - Verra' copiato in %LOCALAPPDATA%\\Programs\\ArtDirector con collegamenti\n"
        "     su Desktop, Menu Start e voce di disinstallazione in App installate.\n\n"
        "3. BACKGROUND & TRAY:\n"
        "   - Chiudendo la finestra con la 'X', Art Director resta attivo in background\n"
        "     nella System Tray (icona vicino all'orologio, stile loopMIDI).\n",
        encoding="utf-8",
    )

    print(f"\nPacchetto pronto per Pen Drive in: {PENDRIVE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
