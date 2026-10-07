"""Lance JARVIS : python run.py  (options : --no-browser, --port 8777)."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser


def open_app_window(url: str) -> None:
    """Ouvre l'interface dans une fenetre type application (Chrome/Edge --app), sinon le navigateur."""
    # On attend que le serveur reponde vraiment (le 1er demarrage peut etre lent).
    import socket
    from urllib.parse import urlparse

    host, port = urlparse(url).hostname, urlparse(url).port
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                break
        except OSError:
            time.sleep(0.5)
    else:
        print("  ! Le serveur ne repond pas : regardez les erreurs ci-dessus.")
        return
    time.sleep(0.3)
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("microsoft-edge") or "",
    ]
    for exe in candidates:
        if exe and os.path.exists(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--window-size=1600,950", "--autoplay-policy=no-user-gesture-required"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                continue
    webbrowser.open(url)


def main() -> None:
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. - assistant IA personnel")
    parser.add_argument("--no-browser", action="store_true", help="ne pas ouvrir l'interface automatiquement")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    if args.port:
        os.environ["JARVIS_PORT"] = str(args.port)

    import uvicorn

    from jarvis.config import HOST, PORT, get_settings

    url = f"http://{HOST}:{PORT}"
    key = "OK" if get_settings().effective_api_key() else "absente (mode autonome)"
    print(f"""
     ╔═══════════════════════════════════════════════╗
     ║   J.A.R.V.I.S.  -  systemes en ligne          ║
     ╚═══════════════════════════════════════════════╝
     Interface : {url}
     Cle API   : {key}
     Arret d'urgence souris : coin de l'ecran | Quitter : Ctrl+C
    """)
    if not args.no_browser:
        threading.Thread(target=open_app_window, args=(url,), daemon=True).start()
    uvicorn.run("jarvis.server:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
