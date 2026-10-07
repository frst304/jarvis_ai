"""Utilitaires multi-plateformes (Windows / macOS / Linux)."""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from .config import IS_LINUX, IS_MAC, IS_WINDOWS

CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


def run(cmd: list[str] | str, timeout: float = 30, shell: bool = False, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        shell=shell,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
        creationflags=CREATE_NO_WINDOW,
        encoding="utf-8",
        errors="replace",
    )


def spawn(cmd: list[str] | str, shell: bool = False) -> None:
    """Lance un programme detache sans attendre."""
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, shell=shell, **kwargs)


def open_with_default(target: str) -> None:
    """Ouvre un fichier, dossier ou URL avec l'application par defaut."""
    if IS_WINDOWS:
        os.startfile(target)  # type: ignore[attr-defined]
    elif IS_MAC:
        spawn(["open", target])
    else:
        spawn(["xdg-open", target])


@lru_cache(maxsize=1)
def gui():
    """Import paresseux de pyautogui (absent ou inutilisable sans ecran)."""
    try:
        import pyautogui  # type: ignore

        pyautogui.FAILSAFE = True  # souris dans un coin de l'ecran = arret d'urgence
        pyautogui.PAUSE = 0.05
        return pyautogui
    except Exception as exc:  # noqa: BLE001 - pas d'ecran, pas de Tk, etc.
        raise RuntimeError(
            "Le controle clavier/souris n'est pas disponible (pyautogui manquant ou pas d'ecran): " + str(exc)
        ) from exc


def gui_available() -> bool:
    try:
        gui()
        return True
    except RuntimeError:
        return False


def which(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def home_folders() -> dict[str, str]:
    home = Path.home()
    candidates = {
        "home": home,
        "bureau": home / "Desktop",
        "documents": home / "Documents",
        "telechargements": home / "Downloads",
        "images": home / "Pictures",
        "musique": home / "Music",
        "videos": home / "Videos" if not IS_MAC else home / "Movies",
    }
    # OneDrive redirige souvent le Bureau/Documents sous Windows
    onedrive = os.environ.get("OneDrive")
    if IS_WINDOWS and onedrive:
        for key, sub in (("bureau", "Desktop"), ("documents", "Documents"), ("images", "Pictures")):
            alt = Path(onedrive) / sub
            if not candidates[key].exists() and alt.exists():
                candidates[key] = alt
    if IS_LINUX:
        for key, xdg in (("bureau", "DESKTOP"), ("documents", "DOCUMENTS"), ("telechargements", "DOWNLOAD")):
            try:
                out = run(["xdg-user-dir", xdg], timeout=3).stdout.strip()
                if out:
                    candidates[key] = Path(out)
            except (OSError, subprocess.SubprocessError):
                pass
    return {k: str(v) for k, v in candidates.items()}


def resolve_path(path: str) -> Path:
    """Transforme 'bureau/rapport.txt', '~/x' ou un chemin absolu en Path."""
    raw = path.strip().strip('"').strip("'")
    folders = home_folders()
    lowered = raw.replace("\\", "/").lower()
    aliases = {
        "desktop": "bureau", "bureau": "bureau", "documents": "documents", "mes documents": "documents",
        "downloads": "telechargements", "telechargements": "telechargements", "téléchargements": "telechargements",
        "pictures": "images", "images": "images", "music": "musique", "musique": "musique",
        "videos": "videos", "vidéos": "videos",
    }
    for alias, key in aliases.items():
        if lowered == alias or lowered.startswith(alias + "/"):
            rest = raw[len(alias):].lstrip("/\\")
            return (Path(folders[key]) / rest).resolve()
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
