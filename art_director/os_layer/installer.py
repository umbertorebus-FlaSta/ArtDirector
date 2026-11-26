"""Cross-platform self-installer, uninstaller, and Pen Drive portable mode helper."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..config.manager import ConfigManager, get_app_base_dir, get_resource_path
from ..config.schema import AppConfig


def get_install_dir() -> Path:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / "Programs" / "ArtDirector"
    if sys.platform == "darwin":
        return Path.home() / "Applications"
    return Path.home() / ".local" / "share" / "art-director"


def is_installed_on_system() -> bool:
    if sys.platform == "win32":
        return (get_install_dir() / "ArtDirector.exe").exists()
    if sys.platform == "darwin":
        return (get_install_dir() / "ArtDirector.app").exists()
    return (Path.home() / ".local" / "bin" / "art-director").exists()


def enable_portable_mode(config: AppConfig) -> tuple[bool, str]:
    """Write portable.flag, config.json, and models/ right beside the executable (Pen Drive mode)."""
    base = get_app_base_dir()
    try:
        (base / "portable.flag").write_text(
            "Art Director Portable Mode enabled.\n", encoding="utf-8"
        )
        (base / "models").mkdir(exist_ok=True)
        cfg_mgr = ConfigManager(base / "config.json")
        cfg_mgr.save(config)
        return True, f"Modalità Portatile attiva in: {base}"
    except Exception as exc:
        return False, f"Impossibile attivare modalità portatile in {base}: {exc}"


def _win_create_shortcut(lnk_path: Path, target_exe: Path, args: str = "", icon_path: Path | None = None, desc: str = "Art Director") -> None:
    lnk_path.parent.mkdir(parents=True, exist_ok=True)
    ico = str(icon_path or target_exe)
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{str(lnk_path).replace(chr(39), chr(39)*2)}'); "
        f"$s.TargetPath = '{str(target_exe).replace(chr(39), chr(39)*2)}'; "
        f"$s.Arguments = '{args.replace(chr(39), chr(39)*2)}'; "
        f"$s.WorkingDirectory = '{str(target_exe.parent).replace(chr(39), chr(39)*2)}'; "
        f"$s.IconLocation = '{ico.replace(chr(39), chr(39)*2)}'; "
        f"$s.Description = '{desc.replace(chr(39), chr(39)*2)}'; "
        "$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps],
        check=True,
        capture_output=True,
        timeout=10,
    )


def install_on_system(copy_models: bool = True) -> tuple[bool, str]:
    """Install the executable onto this machine with Desktop/Menu shortcuts & Uninstall entry."""
    if not getattr(sys, "frozen", False):
        return False, (
            "L'installazione sul sistema va eseguita dal file compilato ArtDirector.exe "
            "(nella cartella ArtDirector_PenDrive)."
        )

    src_exe = Path(sys.executable).resolve()
    src_base = get_app_base_dir()

    if sys.platform == "win32":
        import winreg

        install_dir = get_install_dir()
        install_dir.mkdir(parents=True, exist_ok=True)
        dst_exe = install_dir / "ArtDirector.exe"
        if src_exe != dst_exe:
            shutil.copy2(src_exe, dst_exe)

        # Copy adjacent offline models if present
        src_models = src_base / "models"
        if copy_models and src_models.exists() and src_models.is_dir():
            dst_models = install_dir / "models"
            for item in src_models.iterdir():
                if item.is_dir():
                    target_sub = dst_models / item.name
                    if not target_sub.exists():
                        shutil.copytree(item, target_sub)

        desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
        start_menu = (
            Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Art Director"
        )
        _win_create_shortcut(desktop / "Art Director.lnk", dst_exe)
        _win_create_shortcut(start_menu / "Art Director.lnk", dst_exe)
        _win_create_shortcut(
            start_menu / "Disinstalla Art Director.lnk",
            dst_exe,
            args="--uninstall",
            desc="Disinstalla Art Director",
        )

        uninst_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ArtDirector"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, uninst_key) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Art Director")
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "1.0.0")
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Art Director Audio/Stage")
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(dst_exe))
            winreg.SetValueEx(
                key, "UninstallString", 0, winreg.REG_SZ, f'"{dst_exe}" --uninstall'
            )
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)

        return True, f"Art Director installato in:\n{install_dir}\nCollegamenti creati su Desktop e Menu Start."

    if sys.platform == "darwin":
        app_bundle = src_exe.parents[2] if src_exe.parent.name == "MacOS" else None
        if app_bundle and app_bundle.suffix == ".app":
            dst_app = get_install_dir() / "ArtDirector.app"
            dst_app.parent.mkdir(parents=True, exist_ok=True)
            if app_bundle != dst_app:
                if dst_app.exists():
                    shutil.rmtree(dst_app)
                shutil.copytree(app_bundle, dst_app)
            return True, f"Installato in {dst_app}"
        return False, "Eseguire da ArtDirector.app per installare su macOS."

    # Linux
    bin_dir = Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    dst_bin = bin_dir / "art-director"
    if src_exe != dst_bin:
        shutil.copy2(src_exe, dst_bin)
        dst_bin.chmod(0o755)
    icon_src = get_resource_path("assets/art_director.png")
    icon_dst = Path.home() / ".local" / "share" / "icons" / "art-director.png"
    if icon_src.exists():
        icon_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon_src, icon_dst)
    desktop_entry = Path.home() / ".local" / "share" / "applications" / "art-director.desktop"
    desktop_entry.parent.mkdir(parents=True, exist_ok=True)
    desktop_entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Art Director\n"
        "Comment=Offline Voice Stage Controller\n"
        f"Exec={dst_bin}\n"
        f"Icon={icon_dst}\n"
        "Categories=AudioVideo;Audio;\n"
        "Terminal=false\n",
        encoding="utf-8",
    )
    return True, f"Installato in {dst_bin} e aggiunto al menu applicazioni."


def uninstall_from_system() -> tuple[bool, str]:
    """Remove installed application, shortcuts, and autostart/uninstall registry entries."""
    if sys.platform == "win32":
        import winreg

        for reg_path, val_name in (
            (r"Software\Microsoft\Windows\CurrentVersion\Run", "ArtDirector"),
        ):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_ALL_ACCESS) as k:
                    winreg.DeleteValue(k, val_name)
            except FileNotFoundError:
                pass
        try:
            winreg.DeleteKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ArtDirector",
            )
        except FileNotFoundError:
            pass

        desktop_lnk = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / "Art Director.lnk"
        if desktop_lnk.exists():
            desktop_lnk.unlink()
        start_dir = (
            Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Art Director"
        )
        if start_dir.exists():
            shutil.rmtree(start_dir, ignore_errors=True)

        install_dir = get_install_dir()
        if install_dir.exists():
            # Schedule cleanup after current process exits in case ArtDirector.exe is running from install_dir
            subprocess.Popen(
                ["cmd", "/c", f'timeout /t 2 /nobreak >nul & rmdir /s /q "{install_dir}"'],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        return True, "Art Director disinstallato dal sistema."

    if sys.platform == "darwin":
        dst_app = get_install_dir() / "ArtDirector.app"
        if dst_app.exists():
            shutil.rmtree(dst_app, ignore_errors=True)
        plist = Path.home() / "Library" / "LaunchAgents" / "com.artdirector.daemon.plist"
        if plist.exists():
            plist.unlink()
        return True, "Art Director rimosso da ~/Applications."

    for p in (
        Path.home() / ".local" / "bin" / "art-director",
        Path.home() / ".local" / "share" / "applications" / "art-director.desktop",
        Path.home() / ".config" / "autostart" / "art-director.desktop",
    ):
        if p.exists():
            p.unlink()
    return True, "Art Director rimosso dal sistema."
