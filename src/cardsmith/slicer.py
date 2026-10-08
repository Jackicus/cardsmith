"""Find and launch UltiMaker Cura (native, Flatpak, AppImage, macOS, Windows)."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

FLATPAK_ID = "com.ultimaker.cura"


def find_cura() -> list[str] | None:
    """Command prefix that opens files in Cura, or None if not found."""
    env = os.environ.get("CARDSMITH_CURA")
    if env:
        return [env]
    for name in ("UltiMaker-Cura", "ultimaker-cura", "cura", "Cura"):
        p = shutil.which(name)
        if p:
            return [p]
    if shutil.which("flatpak"):
        try:
            r = subprocess.run(["flatpak", "info", FLATPAK_ID], capture_output=True, timeout=10)
            if r.returncode == 0:
                return ["flatpak", "run", "--file-forwarding", FLATPAK_ID]
        except (OSError, subprocess.SubprocessError):
            pass
    home = Path.home()
    if sys.platform.startswith("linux"):
        for pattern in (str(home / "Applications" / "*Cura*.AppImage"), str(home / "*Cura*.AppImage"),
                        str(home / "Downloads" / "*Cura*.AppImage"), "/opt/*Cura*/*.AppImage"):
            hits = sorted(glob.glob(pattern))
            if hits:
                return [hits[-1]]
    if sys.platform == "darwin":
        for app in sorted(glob.glob("/Applications/UltiMaker Cura*.app")) + sorted(
                glob.glob("/Applications/Ultimaker Cura*.app")):
            return ["open", "-a", app]
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            hits = sorted(glob.glob(os.path.join(base, "UltiMaker Cura*", "UltiMaker-Cura.exe")))
            if hits:
                return [hits[-1]]
    return None


def open_in_cura(files: list[str | Path]) -> bool:
    cmd = find_cura()
    if not cmd:
        return False
    files = [str(Path(f).resolve()) for f in files]
    if "--file-forwarding" in cmd:
        args = [*cmd, "@@", *files, "@@"]
    else:
        args = [*cmd, *files]
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    return True
