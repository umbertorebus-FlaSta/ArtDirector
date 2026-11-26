"""Cross-platform automatic discovery of installed stage applications."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ..config.schema import StageAppEntry


@dataclass
class InstalledProgram:
    name: str
    executable: str
    window_title_hint: str = ""
    category_tier: int = 1  # 0=Stage/Audio/Video, 1=General, 2=Browser/Utility


_TARGET_EXE_CANDIDATES: dict[str, list[str]] = {
    "xr18": ["X-AIR-Edit.exe", "X-AIR-Edit", "X AIR Edit.app"],
    "cakewalk": ["Sonar.exe", "Cakewalk.exe", "Cakewalk.app", "Logic Pro.app"],
    "reaper": ["reaper.exe", "REAPER.app", "reaper"],
    "qlc": ["qlcplus.exe", "Q Light Controller+.app", "QLC+.app", "qlcplus"],
    "virtualdj": ["virtualdj.exe", "VirtualDJ.exe", "VirtualDJ.app", "virtualdj"],
}

_STAGE_KEYWORDS = (
    "x-air",
    "x air",
    "xair",
    "xr18",
    "behringer",
    "flow",
    "midas",
    "sonar",
    "cakewalk",
    "reaper",
    "qlc",
    "virtualdj",
    "virtual dj",
    "vdj",
    "serato",
    "traktor",
    "rekordbox",
    "ableton",
    "cubase",
    "nuendo",
    "studio one",
    "pro tools",
    "fl studio",
    "audacity",
    "dante",
    "focusrite",
    "nexo",
    "touchosc",
    "loopmidi",
    "rtpmidi",
    "midi",
    "asio",
    "dexed",
    "element",
    "obs studio",
    "obs64",
    "davinci",
    "resolve",
    "vlc",
    "resolume",
    "touchdesigner",
    "grandma",
    "chamsys",
    "magicq",
    "dmx",
    "artnet",
    "soundcraft",
    "yamaha",
    "presonus",
    "mackie",
    "allen",
)

_LOW_PRIORITY_KEYWORDS = (
    "chrome",
    "msedge",
    "edge",
    "firefox",
    "brave",
    "opera",
    "discord",
    "teams",
    "zoom",
    "acrobat",
    "reader",
    "python",
    "idle",
    "winrar",
    "7-zip",
    "7zfm",
    "antigravity",
    "vscode",
    "clipgrab",
)


def _compute_category_tier(name: str, executable: str) -> int:
    hay = f"{name} {Path(executable).stem}".lower()
    if any(k in hay for k in _STAGE_KEYWORDS):
        return 0
    if any(k in hay for k in _LOW_PRIORITY_KEYWORDS):
        return 2
    return 1


def infer_app_target_id(app: StageAppEntry) -> str:
    """Infer target_id ('xr18', 'cakewalk', 'reaper', 'qlc', 'virtualdj') from metadata."""
    if app.target_id.strip():
        return app.target_id.strip().lower()
    haystack = " ".join([app.id, app.name, *app.aliases]).lower()
    if any(k in haystack for k in ("x-air", "xair", "x air", "xr18", "behr", "mixer")):
        return "xr18"
    if any(k in haystack for k in ("cakewalk", "sonar", "daw", "logic")):
        return "cakewalk"
    if "reaper" in haystack:
        return "reaper"
    if any(k in haystack for k in ("qlc", "luci", "light")):
        return "qlc"
    if any(k in haystack for k in ("virtualdj", "virtual dj", "vdj")):
        return "virtualdj"
    return ""


def _scan_dir_for_names(
    root: Path, targets_by_lower: dict[str, str], max_depth: int
) -> dict[str, str]:
    found: dict[str, str] = {}
    if not root.exists() or not root.is_dir():
        return found

    stack: list[tuple[Path, int]] = [(root, 0)]
    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", "windows", "$recycle.bin"}

    while stack and len(found) < len(targets_by_lower):
        cur, depth = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    name_l = entry.name.lower()
                    if name_l in targets_by_lower:
                        tid = targets_by_lower[name_l]
                        if tid not in found:
                            found[tid] = entry.path
                    if entry.is_dir(follow_symlinks=False) and depth < max_depth:
                        if name_l not in skip_dirs and not name_l.endswith(".app"):
                            stack.append((Path(entry.path), depth + 1))
        except (PermissionError, OSError):
            continue
    return found


def discover_stage_app_executables() -> dict[str, str]:
    """Return mapping of target_id -> discovered executable/bundle path on this OS."""
    discovered: dict[str, str] = {}
    targets_by_lower: dict[str, str] = {}
    for tid, names in _TARGET_EXE_CANDIDATES.items():
        for name in names:
            targets_by_lower[name.lower()] = tid

    if sys.platform == "win32":
        direct_candidates: list[tuple[str, list[Path]]] = [
            (
                "xr18",
                [
                    Path(r"C:\Program Files\Behringer\X-AIR-Edit\X-AIR-Edit.exe"),
                    Path(r"C:\Program Files (x86)\Behringer\X-AIR-Edit\X-AIR-Edit.exe"),
                ],
            ),
            (
                "cakewalk",
                [
                    Path(r"C:\Program Files\Cakewalk\Sonar\Sonar.exe"),
                    Path(r"C:\Program Files\Cakewalk\Cakewalk Core\Cakewalk.exe"),
                ],
            ),
            (
                "reaper",
                [
                    Path(r"C:\Program Files\REAPER (x64)\reaper.exe"),
                    Path(r"C:\Program Files (x86)\REAPER\reaper.exe"),
                ],
            ),
            (
                "qlc",
                [
                    Path(r"C:\QLC+\qlcplus.exe"),
                    Path(r"C:\Program Files\QLC+\qlcplus.exe"),
                    Path(r"C:\Program Files (x86)\QLC+\qlcplus.exe"),
                ],
            ),
            (
                "virtualdj",
                [
                    Path(r"C:\Program Files\Atomix\VirtualDJ\virtualdj.exe"),
                    Path(r"C:\Program Files (x86)\Atomix\VirtualDJ\virtualdj.exe"),
                ],
            ),
        ]
        for tid, paths in direct_candidates:
            for p in paths:
                if p.exists():
                    discovered[tid] = str(p)
                    break

        remaining = {k: v for k, v in targets_by_lower.items() if v not in discovered}
        if remaining:
            search_roots = [
                (Path(os.environ.get("ProgramFiles", r"C:\Program Files")), 2),
                (Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")), 2),
                (Path.home() / "Desktop", 3),
                (Path.home() / "Downloads", 2),
                (Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))), 2),
            ]
            for root, depth in search_roots:
                if not remaining:
                    break
                hits = _scan_dir_for_names(root, remaining, max_depth=depth)
                for tid, exe_path in hits.items():
                    if tid not in discovered:
                        discovered[tid] = exe_path
                remaining = {k: v for k, v in remaining.items() if v not in discovered}
        return discovered

    if sys.platform == "darwin":
        for root in (Path("/Applications"), Path.home() / "Applications"):
            hits = _scan_dir_for_names(root, targets_by_lower, max_depth=2)
            for tid, app_path in hits.items():
                discovered.setdefault(tid, app_path)
        return discovered

    # Linux
    for tid, names in _TARGET_EXE_CANDIDATES.items():
        for name in names:
            which_path = shutil.which(name)
            if which_path:
                discovered[tid] = which_path
                break
    remaining = {k: v for k, v in targets_by_lower.items() if v not in discovered}
    if remaining:
        for root in (Path("/opt"), Path("/usr/local/bin")):
            hits = _scan_dir_for_names(root, remaining, max_depth=2)
            for tid, exe_path in hits.items():
                discovered.setdefault(tid, exe_path)
    return discovered


def auto_populate_missing_executables(apps: list[StageAppEntry]) -> list[str]:
    """Fill empty StageAppEntry.executable fields from discovered system installs."""
    missing = [a for a in apps if not a.executable.strip()]
    if not missing:
        return []
    found = discover_stage_app_executables()
    updated_names: list[str] = []
    for app in apps:
        if app.executable.strip():
            continue
        tid = infer_app_target_id(app)
        if not app.target_id and tid:
            app.target_id = tid
        if tid in found:
            app.executable = found[tid]
            if not app.process_name.strip():
                app.process_name = Path(found[tid]).stem
            updated_names.append(f"{app.name} -> {found[tid]}")
    return updated_names


_SKIP_APP_WORDS = (
    "uninstall",
    "disinstalla",
    "unins000",
    "uninst",
    "readme",
    "manual",
    "help",
    "documentation",
    "website",
    "license",
    "eula",
    "release notes",
    "changelog",
    "updater",
    "software update",
    "product center",
    "notifier",
    "redistributable",
    "webview",
    "administrative tools",
    "character map",
    "command prompt",
    "disk cleanup",
    "dfrgui",
    "reset configuration",
    "factory default",
    "rewire client mode",
    "show audio configuration",
    "proxy generator",
    "crash",
    "vcredist",
    "audio driver",
    "usb audio driver",
    "setup utility",
    "firmware",
)

_SKIP_EXE_STEMS = {
    "setup",
    "install",
    "unins000",
    "uninst",
    "uninstall",
    "cmd",
    "control",
    "dfrgui",
    "tllegacysetupaddon",
    "ucore",
    "scarlettdfu",
    "ms-teamsupdate",
}

_SKIP_PATH_FRAGMENTS = (
    "\\windows\\",
    "\\package cache\\",
    "\\winsxs\\",
    "\\appdata\\local\\temp\\",
    "edgewebview",
)


def _is_junk_app(name: str, exe_path: str) -> bool:
    exe_l = exe_path.strip().lower()
    if any(frag in exe_l for frag in _SKIP_PATH_FRAGMENTS):
        return True
    stem = Path(exe_path).stem.lower()
    if stem in _SKIP_EXE_STEMS or re.match(r"^unins\d+$", stem):
        return True
    if "setup" in stem and ("redist" in name.lower() or "midi" in name.lower() or "runtime" in name.lower()):
        return True
    low = f"{name} {stem}".lower()
    return any(w in low for w in _SKIP_APP_WORDS)


def _name_quality_score(name: str, exe_path: str, is_curated: bool = False) -> tuple[int, int, int, int]:
    exe_stem = Path(exe_path).stem.lower()
    name_l = name.lower()
    return (
        1 if is_curated else 0,
        1 if (exe_stem and exe_stem in name_l) else 0,
        -name.count("("),
        -len(name),
    )


def _win_resolve_start_menu_shortcuts() -> list[InstalledProgram]:
    ps_script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$roots = @("
        "[Environment]::GetFolderPath('CommonPrograms'),"
        "[Environment]::GetFolderPath('Programs'),"
        "[Environment]::GetFolderPath('DesktopDirectory')"
        "); "
        "foreach ($r in $roots) { "
        "if (Test-Path $r) { "
        "Get-ChildItem -Path $r -Filter '*.lnk' -Recurse -ErrorAction SilentlyContinue | ForEach-Object { "
        "try { "
        "$sc = $ws.CreateShortcut($_.FullName); "
        "$t = $sc.TargetPath; "
        "if ($t -and $t.ToLower().EndsWith('.exe') -and (Test-Path $t)) { "
        "Write-Output ($_.BaseName + '|' + $t) "
        "} "
        "} catch {} "
        "} "
        "} "
        "}"
    )
    results: list[InstalledProgram] = []
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=6.0,
        )
        for line in proc.stdout.splitlines():
            if "|" not in line:
                continue
            name, exe = line.split("|", 1)
            name = name.strip()
            exe = exe.strip()
            if not name or not exe or _is_junk_app(name, exe):
                continue
            results.append(InstalledProgram(name=name, executable=exe, window_title_hint=name))
    except Exception:
        pass
    return results


def _win_scan_uninstall_registry() -> list[InstalledProgram]:
    results: list[InstalledProgram] = []
    try:
        import winreg
    except Exception:
        return results

    hives = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for root_hive, sub in hives:
        try:
            with winreg.OpenKey(root_hive, sub) as k:
                idx = 0
                while True:
                    try:
                        sk = winreg.EnumKey(k, idx)
                        idx += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(k, sk) as ak:
                            try:
                                disp = str(winreg.QueryValueEx(ak, "DisplayName")[0]).strip()
                            except OSError:
                                continue
                            if not disp:
                                continue
                            exe_path = ""
                            try:
                                icon_val = str(winreg.QueryValueEx(ak, "DisplayIcon")[0]).strip()
                                if "," in icon_val:
                                    icon_val = icon_val.split(",", 1)[0]
                                cand = icon_val.strip().strip('"')
                                if cand.lower().endswith(".exe") and Path(cand).exists():
                                    exe_path = cand
                            except OSError:
                                pass

                            if not exe_path or "\\package cache\\" in exe_path.lower():
                                try:
                                    loc = str(winreg.QueryValueEx(ak, "InstallLocation")[0]).strip().strip('"')
                                    if loc and Path(loc).is_dir():
                                        exes = [
                                            p
                                            for p in Path(loc).glob("*.exe")
                                            if not _is_junk_app(disp, str(p))
                                        ]
                                        if exes:
                                            disp_tokens = [t for t in disp.lower().split() if len(t) >= 3]
                                            exes.sort(
                                                key=lambda p: (
                                                    -sum(1 for t in disp_tokens if t in p.stem.lower()),
                                                    len(p.stem),
                                                )
                                            )
                                            exe_path = str(exes[0])
                                except OSError:
                                    pass

                            if exe_path and not _is_junk_app(disp, exe_path):
                                results.append(
                                    InstalledProgram(
                                        name=disp,
                                        executable=exe_path,
                                        window_title_hint=disp,
                                    )
                                )
                    except OSError:
                        continue
        except OSError:
            continue
    return results


def discover_all_installed_programs() -> list[InstalledProgram]:
    """Return prioritized, deduplicated list of installed applications on Windows, macOS, or Linux."""
    by_exe: dict[str, tuple[tuple[int, int, int, int], InstalledProgram]] = {}

    def _add(prog: InstalledProgram, is_curated: bool = False, only_if_missing: bool = False) -> None:
        exe_clean = prog.executable.strip()
        key = exe_clean.lower()
        if not key or _is_junk_app(prog.name, exe_clean):
            return
        if only_if_missing and key in by_exe:
            return
        prog.category_tier = -1 if is_curated else _compute_category_tier(prog.name, exe_clean)
        score = _name_quality_score(prog.name, exe_clean, is_curated=is_curated)
        existing = by_exe.get(key)
        if existing is None or score > existing[0]:
            by_exe[key] = (score, prog)

    # First ensure key stage software (even portable exes like X-AIR-Edit) appear cleanly
    stage_labels = {
        "xr18": ("X-AIR Edit", "X-AIR-Edit"),
        "cakewalk": ("Sonar / Cakewalk", "Cakewalk"),
        "reaper": ("REAPER", "REAPER"),
        "qlc": ("QLC+", "Q Light Controller"),
        "virtualdj": ("VirtualDJ", "VirtualDJ"),
    }
    for tid, exe_path in discover_stage_app_executables().items():
        lbl, hint = stage_labels.get(tid, (Path(exe_path).stem, Path(exe_path).stem))
        _add(InstalledProgram(name=lbl, executable=exe_path, window_title_hint=hint), is_curated=True)

    if sys.platform == "win32":
        for prog in _win_resolve_start_menu_shortcuts():
            _add(prog)
        for prog in _win_scan_uninstall_registry():
            _add(prog)
        # Also scan Registry App Paths
        try:
            import winreg

            for root_hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
                try:
                    with winreg.OpenKey(root_hive, sub) as k:
                        idx = 0
                        while True:
                            try:
                                app_key_name = winreg.EnumKey(k, idx)
                                idx += 1
                                with winreg.OpenKey(k, app_key_name) as ak:
                                    val, _ = winreg.QueryValueEx(ak, "")
                                    exe_str = str(val).strip().strip('"')
                                    if exe_str.lower().endswith(".exe") and Path(exe_str).exists():
                                        nm = Path(app_key_name).stem
                                        _add(
                                            InstalledProgram(name=nm, executable=exe_str, window_title_hint=nm),
                                            only_if_missing=True,
                                        )
                            except OSError:
                                break
                except OSError:
                    continue
        except Exception:
            pass
    elif sys.platform == "darwin":
        for apps_root in (Path("/Applications"), Path.home() / "Applications"):
            if not apps_root.exists():
                continue
            for entry in apps_root.glob("*.app"):
                _add(InstalledProgram(name=entry.stem, executable=str(entry), window_title_hint=entry.stem))
    else:
        for desk_dir in (
            Path("/usr/share/applications"),
            Path.home() / ".local" / "share" / "applications",
        ):
            if not desk_dir.exists():
                continue
            for df in desk_dir.glob("*.desktop"):
                name = ""
                exec_cmd = ""
                for line in df.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.startswith("Name=") and not name:
                        name = line.split("=", 1)[1].strip()
                    elif line.startswith("Exec=") and not exec_cmd:
                        raw_exec = line.split("=", 1)[1].strip()
                        exec_cmd = raw_exec.split()[0] if raw_exec else ""
                if name and exec_cmd:
                    _add(InstalledProgram(name=name, executable=exec_cmd, window_title_hint=name))

    return sorted(
        (pair[1] for pair in by_exe.values()),
        key=lambda p: (p.category_tier, p.name.lower()),
    )
