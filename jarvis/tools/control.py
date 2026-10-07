"""Outils de controle direct : clavier, presse-papiers, fenetres, capture d'ecran."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .. import computer
from ..config import IS_MAC, IS_WINDOWS
from ..osutils import gui, home_folders
from . import ToolError, ToolResult, tool


@tool(
    "type_text",
    "Tape du texte au clavier dans la fenetre active (accents compris), avec Entree optionnelle a la fin. "
    "Ideal pour dicter un message ou remplir un champ deja selectionne.",
    {
        "text": {"type": "string"},
        "press_enter": {"type": "boolean", "description": "Appuyer sur Entree apres la saisie."},
    },
    required=["text"],
    risk="action",
    category="controle",
)
def type_text(text: str, press_enter: bool = False) -> str:
    try:
        computer.type_text(text)
        if press_enter:
            gui().press("enter")
    except (RuntimeError, computer.ComputerError) as exc:
        raise ToolError(str(exc)) from exc
    return f"Texte saisi ({len(text)} caracteres)."


@tool(
    "press_keys",
    "Appuie sur une touche ou un raccourci clavier : 'enter', 'ctrl+c', 'ctrl+shift+esc', 'alt+tab', 'win+d', "
    "'f5', 'cmd+space' (mac)... Peut repeter l'appui.",
    {
        "keys": {"type": "string", "description": "Touche ou combinaison separee par '+'."},
        "repeat": {"type": "integer", "description": "Nombre d'appuis (defaut 1)."},
    },
    required=["keys"],
    risk="action",
    category="controle",
)
def press_keys(keys: str, repeat: int = 1) -> str:
    try:
        computer.press_combo(keys, repeat)
    except (RuntimeError, computer.ComputerError) as exc:
        raise ToolError(str(exc)) from exc
    return f"Touches {keys} pressees" + (f" x{repeat}" if repeat and repeat > 1 else "") + "."


@tool(
    "clipboard",
    "Lit ou remplace le contenu du presse-papiers.",
    {
        "action": {"type": "string", "enum": ["get", "set"]},
        "text": {"type": "string", "description": "Texte a copier (pour set)."},
    },
    required=["action"],
    risk=lambda a: "action" if a.get("action") == "set" else "safe",
    category="controle",
)
def clipboard(action: str, text: str = "") -> str:
    try:
        import pyperclip  # type: ignore
    except ImportError as exc:
        raise ToolError("Module pyperclip non installe.") from exc
    try:
        if action == "set":
            pyperclip.copy(text)
            return "Texte copie dans le presse-papiers."
        content = pyperclip.paste()
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Presse-papiers inaccessible : {exc}") from exc
    if not content:
        return "Le presse-papiers est vide."
    return content if len(content) < 20000 else content[:20000] + "\n...[tronque]"


_WINDOW_KEYS = {
    "show_desktop": {"win": "win+d", "mac": "f11", "linux": "super+d"},
    "minimize": {"win": "win+down", "mac": "cmd+m", "linux": "super+h"},
    "maximize": {"win": "win+up", "mac": "ctrl+cmd+f", "linux": "super+up"},
    "close": {"win": "alt+f4", "mac": "cmd+w", "linux": "alt+f4"},
    "snap_left": {"win": "win+left", "mac": None, "linux": "super+left"},
    "snap_right": {"win": "win+right", "mac": None, "linux": "super+right"},
    "switch": {"win": "alt+tab", "mac": "cmd+tab", "linux": "alt+tab"},
    "task_view": {"win": "win+tab", "mac": "ctrl+up", "linux": "super"},
    "new_virtual_desktop": {"win": "win+ctrl+d", "mac": None, "linux": None},
    "next_virtual_desktop": {"win": "win+ctrl+right", "mac": "ctrl+right", "linux": "ctrl+alt+right"},
    "previous_virtual_desktop": {"win": "win+ctrl+left", "mac": "ctrl+left", "linux": "ctrl+alt+left"},
    "snipping_tool": {"win": "win+shift+s", "mac": "cmd+shift+4", "linux": "print"},
    "emoji_panel": {"win": "win+.", "mac": "ctrl+cmd+space", "linux": None},
    "file_explorer": {"win": "win+e", "mac": None, "linux": "super+e"},
    "run_dialog": {"win": "win+r", "mac": "cmd+space", "linux": "alt+f2"},
    "clipboard_history": {"win": "win+v", "mac": None, "linux": None},
}


@tool(
    "window_action",
    "Gestion des fenetres et du bureau : afficher le bureau, minimiser/maximiser/fermer la fenetre active, "
    "l'ancrer a gauche/droite, changer de fenetre, bureaux virtuels, outil capture, panneau emoji...",
    {"action": {"type": "string", "enum": list(_WINDOW_KEYS)}},
    required=["action"],
    risk=lambda a: "danger" if a.get("action") == "close" else "action",
    category="controle",
    confirm=lambda a: "Fermer la fenetre active ?" if a.get("action") == "close" else f"Action fenetre : {a.get('action')} ?",
)
def window_action(action: str) -> str:
    combo = _WINDOW_KEYS[action]["win" if IS_WINDOWS else ("mac" if IS_MAC else "linux")]
    if not combo:
        raise ToolError("Action non disponible sur ce systeme.")
    try:
        computer.press_combo(combo)
    except (RuntimeError, computer.ComputerError) as exc:
        raise ToolError(str(exc)) from exc
    return f"Action fenetre « {action} » effectuee."


@tool(
    "capture_screen",
    "Prend une capture de l'ecran et la regarde (vision) pour decrire ce qui s'affiche, lire un message d'erreur, "
    "resumer une page... Peut aussi l'enregistrer dans Images/JARVIS.",
    {"save": {"type": "boolean", "description": "Enregistrer la capture dans un fichier."}},
    risk=lambda a: "action" if a.get("save") else "safe",
    category="controle",
)
def capture_screen(save: bool = False) -> ToolResult:
    try:
        frame = computer.screen.capture()
    except computer.ComputerError as exc:
        raise ToolError(str(exc)) from exc
    text = f"Capture d'ecran {frame.width}x{frame.height} (ecran reel {frame.raw_width}x{frame.raw_height})."
    if save:
        import base64

        folder = Path(home_folders()["images"]) / "JARVIS"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"capture_{datetime.now():%Y%m%d_%H%M%S}.png"
        try:
            import mss  # type: ignore
            import mss.tools  # type: ignore

            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[1])
                mss.tools.to_png(shot.rgb, shot.size, output=str(path))
        except Exception:  # noqa: BLE001 - repli : capture reduite
            path.write_bytes(base64.b64decode(frame.png_b64))
        text += f" Enregistree : {path}"
    return ToolResult(text=text, images=[{"media_type": "image/png", "data": frame.png_b64}])
