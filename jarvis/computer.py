"""Prise de controle du PC : captures d'ecran + execution des actions du « computer toolset » de Claude.

Claude voit des captures redimensionnees ; on convertit ses coordonnees vers l'ecran reel.
Securite : deplacer la souris dans un coin de l'ecran declenche l'arret d'urgence (FAILSAFE de pyautogui).
"""

from __future__ import annotations

import base64
import io
import math
import time
from dataclasses import dataclass

from .config import IS_MAC, IS_WINDOWS
from .osutils import gui

MAX_LONG_EDGE = 1280
MAX_VISUAL_TOKENS = 4784


class ComputerError(Exception):
    pass


@dataclass
class Frame:
    png_b64: str
    width: int  # taille envoyee a Claude
    height: int
    raw_width: int  # taille de la capture brute
    raw_height: int
    raw_left: int = 0
    raw_top: int = 0


def _fit(width: int, height: int, long_edge: int = MAX_LONG_EDGE) -> float:
    scale = min(1.0, long_edge / max(width, height))
    tokens_scale = math.sqrt(MAX_VISUAL_TOKENS * 28 * 28 / (width * height))
    return min(scale, tokens_scale)


def _grab():
    try:
        import mss  # type: ignore
        from PIL import Image
    except ImportError as exc:
        raise ComputerError("Modules mss/pillow manquants pour la capture d'ecran.") from exc
    try:
        with mss.mss() as sct:
            mon = sct.monitors[1]  # ecran principal
            shot = sct.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            return img, mon
    except Exception as exc:  # noqa: BLE001
        raise ComputerError(f"Capture d'ecran impossible : {exc}") from exc


def _encode(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class Screen:
    """Etat partage : derniere capture pour la conversion de coordonnees."""

    def __init__(self) -> None:
        self.last: Frame | None = None

    def capture(self) -> Frame:
        from PIL import Image

        img, mon = _grab()
        scale = _fit(*img.size)
        if scale < 1.0:
            img_small = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
        else:
            img_small = img
        frame = Frame(_encode(img_small), img_small.width, img_small.height, img.width, img.height,
                      mon.get("left", 0), mon.get("top", 0))
        self.last = frame
        return frame

    def zoom(self, region: list) -> str:
        from PIL import Image

        frame = self.last or self.capture()
        if not (isinstance(region, list) and len(region) == 4):
            raise ComputerError("region doit etre [x0, y0, x1, y1].")
        x0, y0, x1, y1 = (float(v) for v in region)
        if x1 <= x0 or y1 <= y0:
            raise ComputerError("Region vide.")
        img, _ = _grab()
        fx, fy = img.width / frame.width, img.height / frame.height
        box = (max(0, int(x0 * fx)), max(0, int(y0 * fy)), min(img.width, int(x1 * fx)), min(img.height, int(y1 * fy)))
        crop = img.crop(box)
        scale = _fit(*crop.size, long_edge=1568)
        if scale < 1.0:
            crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))), Image.LANCZOS)
        return _encode(crop)

    # ----- conversion coordonnees (espace capture -> espace pyautogui)
    def to_screen(self, coord) -> tuple[int, int]:
        frame = self.last or self.capture()
        if not (isinstance(coord, (list, tuple)) and len(coord) == 2):
            raise ComputerError("coordinate doit etre [x, y].")
        x, y = float(coord[0]), float(coord[1])
        if not (0 <= x <= frame.width and 0 <= y <= frame.height):
            raise ComputerError(f"Coordonnees hors ecran : {coord} (ecran {frame.width}x{frame.height}).")
        # pyautogui travaille dans son propre espace (points logiques sur Retina,
        # pixels physiques sous Windows) : on convertit proportionnellement.
        gw, gh = gui().size()
        return int(round(x * gw / frame.width)), int(round(y * gh / frame.height))

    def from_screen(self, x: int, y: int) -> tuple[int, int]:
        frame = self.last or self.capture()
        gw, gh = gui().size()
        return int(round(x * frame.width / gw)), int(round(y * frame.height / gh))


screen = Screen()

# ----------------------------------------------------------------- Clavier

_KEYMAP = {
    "return": "enter", "enter": "enter", "kp_enter": "enter", "escape": "esc", "esc": "esc",
    "backspace": "backspace", "back_space": "backspace", "tab": "tab", "space": "space", "delete": "delete",
    "del": "delete", "insert": "insert", "home": "home", "end": "end", "page_up": "pageup", "prior": "pageup",
    "pageup": "pageup", "page_down": "pagedown", "next": "pagedown", "pagedown": "pagedown",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "ctrl": "ctrl", "control": "ctrl", "control_l": "ctrl", "control_r": "ctrlright",
    "alt": "alt", "alt_l": "alt", "alt_r": "altright", "option": "option",
    "shift": "shift", "shift_l": "shift", "shift_r": "shiftright",
    "super": "win", "super_l": "win", "super_r": "win", "win": "win", "windows": "win", "meta": "win",
    "cmd": "command", "command": "command",
    "print": "printscreen", "printscreen": "printscreen", "caps_lock": "capslock", "capslock": "capslock",
    "menu": "apps", "pause": "pause", "num_lock": "numlock", "scroll_lock": "scrolllock",
    "xf86audioraisevolume": "volumeup", "xf86audiolowervolume": "volumedown", "xf86audiomute": "volumemute",
    "xf86audioplay": "playpause", "xf86audionext": "nexttrack", "xf86audioprev": "prevtrack",
    "minus": "-", "plus": "+", "equal": "=", "comma": ",", "period": ".", "slash": "/", "backslash": "\\",
    "semicolon": ";", "apostrophe": "'", "grave": "`", "bracketleft": "[", "bracketright": "]",
}


def map_key(name: str) -> str:
    raw = name.strip()
    low = raw.lower()
    if low in _KEYMAP:
        key = _KEYMAP[low]
    elif len(low) > 1 and low[0] == "f" and low[1:].isdigit():
        key = low
    elif len(raw) == 1:
        key = raw.lower() if raw.isalpha() else raw
    else:
        key = low
    if IS_MAC and key == "win":
        key = "command"
    if IS_MAC and key == "alt":
        key = "option"
    return key


def parse_combo(combo: str) -> list[str]:
    parts = [p for p in combo.replace(" ", "").split("+") if p]
    if combo.strip().endswith("++"):
        parts.append("+")
    return [map_key(p) for p in parts]


def press_combo(combo: str, repeat: int = 1) -> None:
    g = gui()
    keys = parse_combo(combo)
    if not keys:
        raise ComputerError("Touche vide.")
    for k in keys:
        if k not in g.KEYBOARD_KEYS:
            raise ComputerError(f"Touche inconnue : {k}")
    for _ in range(max(1, min(int(repeat or 1), 100))):
        if len(keys) == 1:
            g.press(keys[0])
        else:
            g.hotkey(*keys)
        time.sleep(0.03)


def type_text(text: str) -> None:
    """Tape du texte, accents compris (via le presse-papiers si besoin)."""
    g = gui()
    if text.isascii() and "\n" not in text:
        g.write(text, interval=0.008)
        return
    import pyperclip  # type: ignore

    try:
        previous = pyperclip.paste()
    except Exception:  # noqa: BLE001
        previous = None
    pyperclip.copy(text)
    time.sleep(0.05)
    g.hotkey("command" if IS_MAC else "ctrl", "v")
    time.sleep(0.15)
    if previous is not None:
        try:
            pyperclip.copy(previous)
        except Exception:  # noqa: BLE001
            pass


def _modifiers(text: str | None) -> list[str]:
    return parse_combo(text) if text else []


# ----------------------------------------------------------------- Actions du toolset

MEMBERS = (
    "screenshot", "zoom", "left_click", "right_click", "middle_click", "double_click", "triple_click",
    "left_click_drag", "mouse_move", "left_mouse_down", "left_mouse_up", "cursor_position", "scroll",
    "type", "key", "hold_key", "wait",
)


def execute_action(name: str, args: dict) -> dict:
    """Execute une action du computer toolset. Renvoie {'text':..., 'image': b64|None}."""
    if name not in MEMBERS:
        raise ComputerError(f"Action inconnue : {name}")
    args = args if isinstance(args, dict) else {}
    if name == "screenshot":
        frame = screen.capture()
        return {"text": f"Capture {frame.width}x{frame.height}", "image": frame.png_b64}
    if name == "zoom":
        return {"text": "Zoom", "image": screen.zoom(args.get("region"))}
    if name == "wait":
        time.sleep(max(0.0, min(float(args.get("duration", 1)), 30.0)))
        return {"text": "OK", "image": None}

    g = gui()
    if name in ("left_click", "right_click", "middle_click", "double_click", "triple_click"):
        mods = _modifiers(args.get("text"))
        coord = args.get("coordinate")
        x, y = screen.to_screen(coord) if coord is not None else g.position()
        button = {"right_click": "right", "middle_click": "middle"}.get(name, "left")
        clicks = {"double_click": 2, "triple_click": 3}.get(name, 1)
        for m in mods:
            g.keyDown(m)
        try:
            g.click(x=x, y=y, clicks=clicks, interval=0.06, button=button)
        finally:
            for m in reversed(mods):
                g.keyUp(m)
        return {"text": "OK", "image": None}
    if name == "left_click_drag":
        sx, sy = screen.to_screen(args.get("start_coordinate"))
        ex, ey = screen.to_screen(args.get("coordinate"))
        mods = _modifiers(args.get("text"))
        for m in mods:
            g.keyDown(m)
        try:
            g.moveTo(sx, sy, duration=0.1)
            g.mouseDown(button="left")
            g.moveTo(ex, ey, duration=0.35)
            g.mouseUp(button="left")
        finally:
            for m in reversed(mods):
                g.keyUp(m)
        return {"text": "OK", "image": None}
    if name == "mouse_move":
        x, y = screen.to_screen(args.get("coordinate"))
        g.moveTo(x, y, duration=0.12)
        return {"text": "OK", "image": None}
    if name == "left_mouse_down":
        g.mouseDown(button="left")
        return {"text": "OK", "image": None}
    if name == "left_mouse_up":
        g.mouseUp(button="left")
        return {"text": "OK", "image": None}
    if name == "cursor_position":
        x, y = g.position()
        sx, sy = screen.from_screen(x, y)
        return {"text": f"X={sx}, Y={sy}", "image": None}
    if name == "scroll":
        coord = args.get("coordinate")
        if coord is not None:
            x, y = screen.to_screen(coord)
            g.moveTo(x, y, duration=0.05)
        direction = args.get("scroll_direction", "down")
        amount = max(1, min(int(args.get("scroll_amount", 3) or 3), 50))
        unit = 120 if IS_WINDOWS else (4 if IS_MAC else 1)
        mods = _modifiers(args.get("text"))
        for m in mods:
            g.keyDown(m)
        try:
            if direction in ("up", "down"):
                g.scroll(amount * unit * (1 if direction == "up" else -1))
            else:
                sign = 1 if direction == "right" else -1
                try:
                    g.hscroll(amount * unit * sign)
                except Exception:  # noqa: BLE001 - repli : shift + molette
                    g.keyDown("shift")
                    g.scroll(amount * unit * -sign)
                    g.keyUp("shift")
        finally:
            for m in reversed(mods):
                g.keyUp(m)
        return {"text": "OK", "image": None}
    if name == "type":
        text = args.get("text")
        if not isinstance(text, str):
            raise ComputerError("'text' manquant.")
        type_text(text)
        return {"text": "OK", "image": None}
    if name == "key":
        combo = args.get("text")
        if not isinstance(combo, str) or not combo:
            raise ComputerError("'text' manquant (ex: 'ctrl+s').")
        press_combo(combo, int(args.get("repeat", 1) or 1))
        return {"text": "OK", "image": None}
    if name == "hold_key":
        keys = parse_combo(str(args.get("text", "")))
        duration = max(0.0, min(float(args.get("duration", 0.5)), 30.0))
        for k in keys:
            g.keyDown(k)
        time.sleep(duration)
        for k in reversed(keys):
            g.keyUp(k)
        return {"text": "OK", "image": None}
    raise ComputerError(f"Action non geree : {name}")
