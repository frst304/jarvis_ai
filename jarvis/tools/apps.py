"""Outils applications : ouvrir/fermer des logiciels, sites, recherches, musique, fenetres."""

from __future__ import annotations

import re
import time
import webbrowser
from urllib.parse import quote_plus

import httpx
import psutil

from ..config import IS_MAC, IS_WINDOWS
from ..osutils import gui, open_with_default, resolve_path, run, spawn, which
from . import ToolError, tool

# alias -> (windows, mac, linux, noms de processus)
APPS: dict[str, dict] = {
    "chrome": {"win": "chrome", "mac": "Google Chrome", "linux": ["google-chrome", "chromium", "chromium-browser"], "proc": ["chrome", "google chrome"]},
    "firefox": {"win": "firefox", "mac": "Firefox", "linux": ["firefox"], "proc": ["firefox"]},
    "edge": {"win": "msedge", "mac": "Microsoft Edge", "linux": ["microsoft-edge"], "proc": ["msedge", "microsoft edge"]},
    "navigateur": {"win": "https://www.google.com", "mac": "Safari", "linux": ["xdg-open https://www.google.com"], "proc": []},
    "vscode": {"win": "code", "mac": "Visual Studio Code", "linux": ["code"], "proc": ["code"]},
    "notepad": {"win": "notepad", "mac": "TextEdit", "linux": ["gedit", "gnome-text-editor", "kate", "mousepad"], "proc": ["notepad", "textedit", "gedit"]},
    "calculatrice": {"win": "calc", "mac": "Calculator", "linux": ["gnome-calculator", "kcalc", "galculator"], "proc": ["calculatorapp", "calculator", "gnome-calculator"]},
    "explorateur": {"win": "explorer", "mac": "Finder", "linux": ["nautilus", "dolphin", "thunar", "nemo"], "proc": []},
    "terminal": {"win": "wt", "mac": "Terminal", "linux": ["gnome-terminal", "konsole", "xfce4-terminal", "xterm"], "proc": ["windowsterminal", "terminal"]},
    "cmd": {"win": "cmd", "mac": "Terminal", "linux": ["gnome-terminal", "xterm"], "proc": ["cmd"]},
    "powershell": {"win": "powershell", "mac": "Terminal", "linux": ["pwsh"], "proc": ["powershell"]},
    "paint": {"win": "mspaint", "mac": "Preview", "linux": ["pinta", "kolourpaint"], "proc": ["mspaint"]},
    "word": {"win": "winword", "mac": "Microsoft Word", "linux": ["libreoffice --writer"], "proc": ["winword", "microsoft word"]},
    "excel": {"win": "excel", "mac": "Microsoft Excel", "linux": ["libreoffice --calc"], "proc": ["excel", "microsoft excel"]},
    "powerpoint": {"win": "powerpnt", "mac": "Microsoft PowerPoint", "linux": ["libreoffice --impress"], "proc": ["powerpnt", "microsoft powerpoint"]},
    "outlook": {"win": "outlook", "mac": "Microsoft Outlook", "linux": ["thunderbird"], "proc": ["outlook"]},
    "teams": {"win": "msteams:", "mac": "Microsoft Teams", "linux": ["teams"], "proc": ["ms-teams", "teams"]},
    "spotify": {"win": "spotify:", "mac": "Spotify", "linux": ["spotify"], "proc": ["spotify"]},
    "discord": {"win": "discord:", "mac": "Discord", "linux": ["discord"], "proc": ["discord"]},
    "steam": {"win": "steam://open/main", "mac": "Steam", "linux": ["steam"], "proc": ["steam", "steamwebhelper"]},
    "vlc": {"win": "vlc", "mac": "VLC", "linux": ["vlc"], "proc": ["vlc"]},
    "parametres": {"win": "ms-settings:", "mac": "System Settings", "linux": ["gnome-control-center"], "proc": ["systemsettings"]},
    "gestionnaire des taches": {"win": "taskmgr", "mac": "Activity Monitor", "linux": ["gnome-system-monitor"], "proc": ["taskmgr"]},
    "panneau de configuration": {"win": "control", "mac": "System Settings", "linux": ["gnome-control-center"], "proc": []},
    "camera": {"win": "microsoft.windows.camera:", "mac": "Photo Booth", "linux": ["cheese"], "proc": ["windowscamera"]},
    "photos": {"win": "ms-photos:", "mac": "Photos", "linux": ["eog"], "proc": ["photos"]},
    "horloge": {"win": "ms-clock:", "mac": "Clock", "linux": ["gnome-clocks"], "proc": []},
    "store": {"win": "ms-windows-store:", "mac": "App Store", "linux": ["gnome-software"], "proc": []},
    "mail": {"win": "outlookmail:", "mac": "Mail", "linux": ["thunderbird"], "proc": []},
    "obs": {"win": "obs64", "mac": "OBS", "linux": ["obs"], "proc": ["obs64", "obs"]},
    "whatsapp": {"win": "whatsapp:", "mac": "WhatsApp", "linux": ["whatsapp-for-linux"], "proc": ["whatsapp"]},
    "slack": {"win": "slack:", "mac": "Slack", "linux": ["slack"], "proc": ["slack"]},
    "zoom": {"win": "zoommtg:", "mac": "zoom.us", "linux": ["zoom"], "proc": ["zoom"]},
    "netflix": {"win": "https://www.netflix.com", "mac": "https://www.netflix.com", "linux": ["xdg-open https://www.netflix.com"], "proc": []},
}

ALIASES = {
    "google chrome": "chrome", "google": "chrome", "mozilla": "firefox", "microsoft edge": "edge",
    "internet": "navigateur", "browser": "navigateur", "le navigateur": "navigateur", "web": "navigateur",
    "visual studio code": "vscode", "vs code": "vscode", "code": "vscode", "editeur de code": "vscode",
    "bloc-notes": "notepad", "bloc notes": "notepad", "blocnote": "notepad", "notes": "notepad", "textedit": "notepad",
    "calculator": "calculatrice", "calc": "calculatrice", "calculette": "calculatrice",
    "explorer": "explorateur", "explorateur de fichiers": "explorateur", "fichiers": "explorateur", "finder": "explorateur",
    "invite de commandes": "cmd", "console": "terminal", "windows terminal": "terminal",
    "reglages": "parametres", "settings": "parametres", "paramètres": "parametres", "réglages": "parametres",
    "task manager": "gestionnaire des taches", "gestionnaire de taches": "gestionnaire des taches",
    "gestionnaire des tâches": "gestionnaire des taches", "moniteur d'activite": "gestionnaire des taches",
    "microsoft word": "word", "microsoft excel": "excel", "microsoft powerpoint": "powerpoint", "ppt": "powerpoint",
    "microsoft teams": "teams", "musique": "spotify", "webcam": "camera", "caméra": "camera",
    "obs studio": "obs", "control panel": "panneau de configuration",
}


def _canonical(name: str) -> str:
    key = name.strip().lower()
    key = re.sub(r"^(l'|le |la |les |l |mon |ma |application |appli |logiciel )", "", key).strip()
    return ALIASES.get(key, key)


def _windows_search_launch(name: str) -> None:
    """Repli : ouvre le menu Demarrer, tape le nom, Entree."""
    g = gui()
    g.press("win")
    time.sleep(0.6)
    g.write(name, interval=0.02)
    time.sleep(0.9)
    g.press("enter")


@tool(
    "open_application",
    "Ouvre une application installee sur le PC (navigateur, Chrome, VS Code, Word, Excel, Spotify, Discord, "
    "calculatrice, explorateur, parametres, gestionnaire des taches, terminal, etc.). Accepte n'importe quel nom : "
    "si l'application n'est pas connue, JARVIS la cherche dans le menu Demarrer / Spotlight.",
    {"name": {"type": "string", "description": "Nom de l'application, ex: 'chrome', 'spotify', 'word'."}},
    required=["name"],
    risk="action",
    category="applications",
)
def open_application(name: str) -> str:
    key = _canonical(name)
    entry = APPS.get(key)
    if IS_WINDOWS:
        target = entry["win"] if entry else None
        if target:
            if ":" in target and not target.startswith("http"):
                open_with_default(target)
            elif target.startswith("http"):
                webbrowser.open(target)
            else:
                spawn(f'start "" {target}', shell=True)
            return f"{name} ouvert."
        exe = which(key, key + ".exe")
        if exe:
            spawn([exe])
            return f"{name} ouvert."
        _windows_search_launch(name)
        return f"{name} lance via le menu Demarrer."
    if IS_MAC:
        target = entry["mac"] if entry else name
        if target.startswith("http"):
            webbrowser.open(target)
            return f"{name} ouvert."
        result = run(["open", "-a", target], timeout=15)
        if result.returncode != 0:
            raise ToolError(f"Application introuvable : {name}.")
        return f"{name} ouvert."
    candidates = entry["linux"] if entry else [key, key.replace(" ", "-")]
    for cand in candidates:
        parts = cand.split()
        if which(parts[0]):
            spawn(parts)
            return f"{name} ouvert."
    if which("gtk-launch"):
        res = run(["gtk-launch", key], timeout=10)
        if res.returncode == 0:
            return f"{name} ouvert."
    raise ToolError(f"Application introuvable : {name}.")


@tool(
    "close_application",
    "Ferme proprement une application ouverte (toutes ses fenetres).",
    {"name": {"type": "string", "description": "Nom de l'application a fermer."}},
    required=["name"],
    risk="action",
    category="applications",
)
def close_application(name: str) -> str:
    key = _canonical(name)
    entry = APPS.get(key)
    proc_names = [p.lower() for p in (entry["proc"] if entry else [])] or [key]
    if IS_MAC and entry:
        run(["osascript", "-e", f'quit app "{entry["mac"]}"'], timeout=10)
        return f"{name} ferme."
    closed = 0
    seen: set[str] = set()
    for p in psutil.process_iter(["name"]):
        pname = (p.info.get("name") or "").lower().removesuffix(".exe")
        if any(pname == n or (len(n) > 3 and n in pname) for n in proc_names):
            if IS_WINDOWS:
                exe = (p.info.get("name") or "")
                if exe not in seen:
                    seen.add(exe)
                    run(["taskkill", "/IM", exe], timeout=10)
                closed += 1
            else:
                try:
                    p.terminate()
                    closed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
    if not closed:
        raise ToolError(f"{name} ne semble pas ouvert.")
    return f"{name} ferme."


@tool(
    "open_url",
    "Ouvre une adresse web (ou un lien mailto:, tel:, etc.) dans le navigateur par defaut.",
    {"url": {"type": "string", "description": "URL complete, ex: https://www.lemonde.fr"}},
    required=["url"],
    risk="action",
    category="applications",
)
def open_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
        url = "https://" + url
    if url.lower().startswith(("file:", "javascript:")):
        raise ToolError("Ce type de lien n'est pas autorise.")
    webbrowser.open(url)
    return f"Ouverture de {url}"


SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "wikipedia": "https://fr.wikipedia.org/w/index.php?search={q}",
    "maps": "https://www.google.com/maps/search/{q}",
    "images": "https://www.google.com/search?tbm=isch&q={q}",
    "amazon": "https://www.amazon.fr/s?k={q}",
    "github": "https://github.com/search?q={q}",
    "reddit": "https://www.reddit.com/search/?q={q}",
    "traduction": "https://translate.google.com/?sl=auto&tl=fr&text={q}",
    "itineraire": "https://www.google.com/maps/dir/?api=1&destination={q}",
}


@tool(
    "search_in_browser",
    "Lance une recherche dans le navigateur de l'utilisateur (Google, YouTube, Maps, Amazon, Wikipedia, "
    "GitHub, Reddit, images, traduction, itineraire). Pour repondre soi-meme a une question, preferer web_search.",
    {
        "query": {"type": "string"},
        "engine": {"type": "string", "enum": list(SEARCH_ENGINES), "description": "Moteur (defaut google)."},
    },
    required=["query"],
    risk="action",
    category="applications",
)
def search_in_browser(query: str, engine: str = "google") -> str:
    webbrowser.open(SEARCH_ENGINES.get(engine, SEARCH_ENGINES["google"]).format(q=quote_plus(query)))
    return f"Recherche « {query} » ouverte sur {engine}."


def youtube_first_video(query: str) -> str | None:
    try:
        r = httpx.get(
            "https://www.youtube.com/results",
            params={"search_query": query},
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "fr-FR,fr;q=0.9"},
            timeout=8,
            follow_redirects=True,
        )
        m = re.search(r'"videoId":"([\w-]{11})"', r.text)
        return m.group(1) if m else None
    except httpx.HTTPError:
        return None


@tool(
    "play_media",
    "Joue de la musique ou une video : lance directement la premiere video YouTube correspondante, "
    "ou ouvre la recherche dans Spotify / Deezer / SoundCloud.",
    {
        "query": {"type": "string", "description": "Titre, artiste, playlist, ex: 'Back in Black AC/DC'."},
        "platform": {"type": "string", "enum": ["youtube", "spotify", "deezer", "soundcloud"], "description": "Defaut youtube."},
    },
    required=["query"],
    risk="action",
    category="media",
)
def play_media(query: str, platform: str = "youtube") -> str:
    if platform == "spotify":
        try:
            open_with_default("spotify:search:" + quote_plus(query).replace("+", "%20"))
        except OSError:
            webbrowser.open("https://open.spotify.com/search/" + quote_plus(query))
        return f"Recherche « {query} » ouverte dans Spotify."
    if platform == "deezer":
        webbrowser.open("https://www.deezer.com/search/" + quote_plus(query))
        return f"Recherche « {query} » ouverte sur Deezer."
    if platform == "soundcloud":
        webbrowser.open("https://soundcloud.com/search?q=" + quote_plus(query))
        return f"Recherche « {query} » ouverte sur SoundCloud."
    vid = youtube_first_video(query)
    if vid:
        webbrowser.open(f"https://www.youtube.com/watch?v={vid}&autoplay=1")
        return f"Lecture de « {query} » sur YouTube (video {vid})."
    webbrowser.open(SEARCH_ENGINES["youtube"].format(q=quote_plus(query)))
    return f"Resultats YouTube pour « {query} » ouverts."


@tool(
    "open_path",
    "Ouvre un fichier ou un dossier avec l'application par defaut (ex: 'documents', 'bureau/rapport.pdf', "
    "'C:/Users/moi/Downloads').",
    {"path": {"type": "string"}},
    required=["path"],
    risk="action",
    category="fichiers",
)
def open_path(path: str) -> str:
    p = resolve_path(path)
    if not p.exists():
        raise ToolError(f"Introuvable : {p}")
    open_with_default(str(p))
    return f"Ouverture de {p}"


@tool(
    "list_windows",
    "Liste les fenetres ouvertes (titres).",
    category="applications",
)
def list_windows() -> list[str]:
    if IS_WINDOWS:
        try:
            import pygetwindow as gw  # type: ignore

            return sorted({t for t in gw.getAllTitles() if t.strip()})
        except ImportError as exc:
            raise ToolError("Module pygetwindow non installe.") from exc
    if IS_MAC:
        script = 'tell application "System Events" to get name of (processes where background only is false)'
        return [s.strip() for s in run(["osascript", "-e", script], timeout=8).stdout.split(",") if s.strip()]
    if which("wmctrl"):
        return [line.split(None, 3)[-1] for line in run(["wmctrl", "-l"], timeout=5).stdout.splitlines() if line]
    raise ToolError("Listing des fenetres indisponible (installez wmctrl).")


@tool(
    "focus_window",
    "Met au premier plan une fenetre dont le titre contient le texte donne (ex: 'Chrome', 'Excel').",
    {"title": {"type": "string"}},
    required=["title"],
    risk="action",
    category="applications",
)
def focus_window(title: str) -> str:
    if IS_WINDOWS:
        try:
            import pygetwindow as gw  # type: ignore
        except ImportError as exc:
            raise ToolError("Module pygetwindow non installe.") from exc
        wins = [w for w in gw.getAllWindows() if title.lower() in w.title.lower() and w.title.strip()]
        if not wins:
            raise ToolError(f"Aucune fenetre « {title} ».")
        w = wins[0]
        try:
            if w.isMinimized:
                w.restore()
            gui().press("alt")  # contourne la protection anti-vol de focus de Windows
            w.activate()
        except Exception:  # noqa: BLE001
            w.minimize()
            w.restore()
        return f"Fenetre « {w.title} » au premier plan."
    if IS_MAC:
        res = run(["osascript", "-e", f'tell application "{title}" to activate'], timeout=8)
        if res.returncode != 0:
            raise ToolError(f"Application « {title} » introuvable.")
        return f"{title} au premier plan."
    if which("wmctrl"):
        res = run(["wmctrl", "-a", title], timeout=5)
        if res.returncode != 0:
            raise ToolError(f"Aucune fenetre « {title} ».")
        return f"Fenetre « {title} » au premier plan."
    raise ToolError("Installez wmctrl pour gerer les fenetres.")
