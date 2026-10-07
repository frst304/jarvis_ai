"""Outils systeme : etat de la machine, processus, alimentation, volume, luminosite, reseau."""

from __future__ import annotations

import os
import threading
import time

import psutil

from .. import monitor
from ..config import IS_MAC, IS_WINDOWS
from ..osutils import gui, run, which
from . import ToolError, tool


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}j")
    if h:
        parts.append(f"{h}h")
    parts.append(f"{m}min")
    return " ".join(parts)


@tool(
    "get_system_status",
    "Etat complet du PC : CPU, RAM, disque, reseau, batterie, temperature, GPU, uptime, OS et processus "
    "les plus gourmands. A utiliser quand l'utilisateur demande comment va son ordinateur, la batterie, "
    "la memoire, si le PC rame, etc.",
    category="systeme",
)
def get_system_status() -> dict:
    snap = monitor.snapshot(include_processes=False)
    time.sleep(0.4)  # mesure CPU plus fiable
    snap = monitor.snapshot(include_processes=True)
    snap["identity"] = monitor.system_identity()
    snap["gpu"] = monitor.gpu_info()
    snap["uptime"] = _fmt_duration(snap.pop("uptime_s"))
    snap.pop("cpu_cores", None)
    snap["local_ip"] = monitor.local_ip()
    return snap


@tool(
    "list_processes",
    "Liste les processus en cours (tries par CPU, memoire ou nom), avec filtre optionnel sur le nom.",
    {
        "sort_by": {"type": "string", "enum": ["cpu", "memory", "name"], "description": "Critere de tri."},
        "limit": {"type": "integer", "description": "Nombre maximum de resultats (defaut 15)."},
        "name_filter": {"type": "string", "description": "Ne garder que les processus dont le nom contient ce texte."},
    },
    category="systeme",
)
def list_processes(sort_by: str = "cpu", limit: int = 15, name_filter: str = "") -> list[dict]:
    for p in psutil.process_iter():
        try:
            p.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    time.sleep(0.5)
    return monitor.top_processes(max(1, min(limit, 100)), sort_by, name_filter)


@tool(
    "kill_process",
    "Termine un processus par nom (ex: 'chrome.exe', 'spotify') ou par PID. Ferme TOUTES les instances "
    "correspondant au nom.",
    {
        "name_or_pid": {"type": "string", "description": "Nom du processus ou PID."},
        "force": {"type": "boolean", "description": "Forcer l'arret (kill) au lieu d'une fermeture propre."},
    },
    required=["name_or_pid"],
    risk="danger",
    category="systeme",
    confirm=lambda a: f"Terminer le processus « {a.get('name_or_pid')} » ?",
)
def kill_process(name_or_pid: str, force: bool = False) -> str:
    targets: list[psutil.Process] = []
    if name_or_pid.strip().isdigit():
        try:
            targets.append(psutil.Process(int(name_or_pid)))
        except psutil.NoSuchProcess as exc:
            raise ToolError(f"Aucun processus avec le PID {name_or_pid}.") from exc
    else:
        wanted = name_or_pid.lower().removesuffix(".exe")
        for p in psutil.process_iter(["name"]):
            name = (p.info.get("name") or "").lower().removesuffix(".exe")
            if name == wanted or (len(wanted) > 3 and wanted in name):
                targets.append(p)
    if not targets:
        raise ToolError(f"Aucun processus ne correspond a « {name_or_pid} ».")
    protected = {"system", "csrss", "wininit", "winlogon", "services", "lsass", "smss", "init", "systemd", "launchd", "kernel_task"}
    me = os.getpid()
    done = 0
    for p in targets:
        try:
            if p.pid == me or (p.name() or "").lower().removesuffix(".exe") in protected:
                continue
            p.kill() if force else p.terminate()
            done += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not done:
        raise ToolError("Impossible de terminer ce processus (protege ou acces refuse).")
    return f"{done} processus termine(s)."


_POWER = ("shutdown", "restart", "sleep", "hibernate", "lock", "logout", "cancel")


def _power_command(action: str, delay: int) -> list[str] | str | None:
    if IS_WINDOWS:
        return {
            "shutdown": ["shutdown", "/s", "/t", str(delay)],
            "restart": ["shutdown", "/r", "/t", str(delay)],
            "logout": ["shutdown", "/l"],
            "hibernate": ["shutdown", "/h"],
            "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
            "cancel": ["shutdown", "/a"],
        }[action]
    if IS_MAC:
        return {
            "shutdown": ["osascript", "-e", 'tell app "System Events" to shut down'],
            "restart": ["osascript", "-e", 'tell app "System Events" to restart'],
            "logout": ["osascript", "-e", 'tell app "System Events" to log out'],
            "sleep": ["pmset", "sleepnow"],
            "hibernate": ["pmset", "sleepnow"],
            "lock": ["osascript", "-e", 'tell application "System Events" to keystroke "q" using {control down, command down}'],
            "cancel": None,
        }[action]
    lock = ["loginctl", "lock-session"] if which("loginctl") else ["xdg-screensaver", "lock"]
    return {
        "shutdown": ["systemctl", "poweroff"],
        "restart": ["systemctl", "reboot"],
        "logout": ["loginctl", "terminate-user", os.environ.get("USER", "")],
        "sleep": ["systemctl", "suspend"],
        "hibernate": ["systemctl", "hibernate"],
        "lock": lock,
        "cancel": None,
    }[action]


_pending_timer: threading.Timer | None = None


@tool(
    "power_action",
    "Alimentation et session : eteindre, redemarrer, mettre en veille, hiberner, verrouiller la session, "
    "se deconnecter, ou annuler un arret programme. Un delai en secondes est possible.",
    {
        "action": {"type": "string", "enum": list(_POWER)},
        "delay_seconds": {"type": "integer", "description": "Delai avant l'action (defaut 0 ; 30 conseille pour shutdown/restart)."},
    },
    required=["action"],
    risk=lambda a: "action" if a.get("action") in ("lock", "cancel") else "danger",
    category="systeme",
    confirm=lambda a: {
        "shutdown": "Eteindre l'ordinateur", "restart": "Redemarrer l'ordinateur", "sleep": "Mettre le PC en veille",
        "hibernate": "Mettre le PC en veille prolongee", "logout": "Fermer la session", "lock": "Verrouiller la session",
        "cancel": "Annuler l'arret programme",
    }.get(a.get("action"), "Action d'alimentation") + (f" dans {a.get('delay_seconds')} s" if a.get("delay_seconds") else "") + " ?",
)
def power_action(action: str, delay_seconds: int = 0) -> str:
    global _pending_timer
    delay = max(0, min(int(delay_seconds or 0), 86400))
    if action == "cancel":
        if _pending_timer:
            _pending_timer.cancel()
            _pending_timer = None
        cmd = _power_command("cancel", 0)
        if cmd:
            run(cmd, timeout=10)
        return "Arret programme annule."
    cmd = _power_command(action, delay)
    if cmd is None:
        raise ToolError("Action non supportee sur ce systeme.")
    native_delay = IS_WINDOWS and action in ("shutdown", "restart")
    if delay and not native_delay:
        _pending_timer = threading.Timer(delay, lambda: run(cmd, timeout=30))
        _pending_timer.daemon = True
        _pending_timer.start()
        return f"Action « {action} » programmee dans {delay} secondes."
    result = run(cmd, timeout=30)
    if result.returncode not in (0, None) and action != "lock":
        raise ToolError(result.stderr.strip() or f"Echec de l'action {action}.")
    return f"Action « {action} » executee" + (f" (dans {delay} s)." if delay else ".")


# ---------------------------------------------------------------- Volume

def _win_endpoint():
    import comtypes  # type: ignore
    from pycaw.pycaw import AudioUtilities  # type: ignore

    comtypes.CoInitialize()
    speakers = AudioUtilities.GetSpeakers()
    endpoint = getattr(speakers, "EndpointVolume", None)
    if endpoint is not None:
        return endpoint
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL  # type: ignore
    from pycaw.pycaw import IAudioEndpointVolume  # type: ignore

    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def get_volume() -> int | None:
    try:
        if IS_WINDOWS:
            return round(_win_endpoint().GetMasterVolumeLevelScalar() * 100)
        if IS_MAC:
            return int(run(["osascript", "-e", "output volume of (get volume settings)"], timeout=5).stdout.strip())
        if which("pactl"):
            out = run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], timeout=5).stdout
            for token in out.split():
                if token.endswith("%"):
                    return int(token.rstrip("%"))
        if which("amixer"):
            out = run(["amixer", "get", "Master"], timeout=5).stdout
            import re

            m = re.search(r"\[(\d+)%\]", out)
            if m:
                return int(m.group(1))
    except Exception:  # noqa: BLE001
        return None
    return None


def _set_volume_level(level: int) -> bool:
    level = max(0, min(100, level))
    try:
        if IS_WINDOWS:
            ep = _win_endpoint()
            ep.SetMute(0, None)
            ep.SetMasterVolumeLevelScalar(level / 100, None)
            return True
        if IS_MAC:
            run(["osascript", "-e", f"set volume output volume {level}"], timeout=5)
            return True
        if which("pactl"):
            run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], timeout=5)
            run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"], timeout=5)
            return True
        if which("amixer"):
            run(["amixer", "-q", "sset", "Master", f"{level}%", "unmute"], timeout=5)
            return True
    except Exception:  # noqa: BLE001
        pass
    # Repli universel : touches multimedia (2 % par appui sous Windows)
    current = get_volume()
    g = gui()
    if current is None:
        g.press("volumedown", presses=50)
        current = 0
    diff = level - current
    key = "volumeup" if diff > 0 else "volumedown"
    g.press(key, presses=abs(diff) // 2)
    return True


def _set_mute(mute: bool) -> None:
    if IS_WINDOWS:
        try:
            _win_endpoint().SetMute(1 if mute else 0, None)
            return
        except Exception:  # noqa: BLE001
            gui().press("volumemute")
            return
    if IS_MAC:
        run(["osascript", "-e", f"set volume output muted {'true' if mute else 'false'}"], timeout=5)
    elif which("pactl"):
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if mute else "0"], timeout=5)
    elif which("amixer"):
        run(["amixer", "-q", "sset", "Master", "mute" if mute else "unmute"], timeout=5)
    else:
        gui().press("volumemute")


@tool(
    "set_volume",
    "Regle le volume sonore du PC : niveau absolu (0-100), variation relative (+/-), couper ou retablir le son. "
    "Sans parametre, renvoie le volume actuel.",
    {
        "level": {"type": "integer", "description": "Volume cible 0-100."},
        "change": {"type": "integer", "description": "Variation relative, ex: 10 ou -20."},
        "mute": {"type": "boolean", "description": "true pour couper le son, false pour le retablir."},
    },
    risk="action",
    category="systeme",
)
def set_volume(level: int | None = None, change: int | None = None, mute: bool | None = None) -> str:
    if mute is not None:
        _set_mute(mute)
        if mute:
            return "Son coupe."
        if level is None and change is None:
            return "Son retabli."
    if level is None and change is not None:
        current = get_volume()
        level = (current if current is not None else 50) + change
    if level is not None:
        _set_volume_level(int(level))
        return f"Volume regle a {max(0, min(100, int(level)))} %."
    current = get_volume()
    return f"Volume actuel : {current} %." if current is not None else "Volume actuel inconnu."


@tool(
    "set_brightness",
    "Regle la luminosite de l'ecran (0-100) ou la lit si aucun niveau n'est donne.",
    {"level": {"type": "integer", "description": "Luminosite cible 0-100."},
     "change": {"type": "integer", "description": "Variation relative (+/-)."}},
    risk="action",
    category="systeme",
)
def set_brightness(level: int | None = None, change: int | None = None) -> str:
    try:
        import screen_brightness_control as sbc  # type: ignore
    except ImportError as exc:
        raise ToolError("Module screen-brightness-control non installe.") from exc
    try:
        current = sbc.get_brightness()
        current = current[0] if isinstance(current, list) else current
        if level is None and change is None:
            return f"Luminosite actuelle : {current} %."
        target = level if level is not None else (current or 50) + (change or 0)
        target = max(0, min(100, int(target)))
        sbc.set_brightness(target)
        return f"Luminosite reglee a {target} %."
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Impossible de regler la luminosite (ecran externe ?) : {exc}") from exc


@tool(
    "network_info",
    "Informations reseau : IP locale, IP publique et localisation approximative, nom du Wi-Fi, "
    "et test de latence (ping) vers un hote.",
    {"ping_host": {"type": "string", "description": "Hote a pinger (defaut: 1.1.1.1)."}},
    category="systeme",
)
def network_info(ping_host: str = "1.1.1.1") -> dict:
    import httpx

    info: dict = {"local_ip": monitor.local_ip()}
    try:
        r = httpx.get("https://ipwho.is/", timeout=6)
        j = r.json()
        info["public_ip"] = j.get("ip")
        info["location"] = f"{j.get('city')}, {j.get('region')}, {j.get('country')}"
        info["isp"] = (j.get("connection") or {}).get("isp")
    except Exception:  # noqa: BLE001
        info["public_ip"] = "indisponible (hors ligne ?)"
    try:
        if IS_WINDOWS:
            out = run(["netsh", "wlan", "show", "interfaces"], timeout=6).stdout
            for line in out.splitlines():
                if line.strip().lower().startswith("ssid") and "bssid" not in line.lower():
                    info["wifi"] = line.split(":", 1)[1].strip()
                    break
        elif IS_MAC:
            out = run(["networksetup", "-getairportnetwork", "en0"], timeout=6).stdout
            info["wifi"] = out.split(":", 1)[-1].strip()
        elif which("iwgetid"):
            info["wifi"] = run(["iwgetid", "-r"], timeout=6).stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    host = ping_host.strip() or "1.1.1.1"
    if not all(c.isalnum() or c in ".-:" for c in host):
        raise ToolError("Hote invalide.")
    cmd = ["ping", "-n" if IS_WINDOWS else "-c", "3", host]
    try:
        out = run(cmd, timeout=15).stdout
        import re

        times = [float(t.replace(",", ".")) for t in re.findall(r"[=<]\s*([\d.,]+)\s*ms", out)]
        info["ping"] = {"host": host, "avg_ms": round(sum(times) / len(times), 1) if times else None,
                        "replies": len(times)}
    except Exception:  # noqa: BLE001
        info["ping"] = {"host": host, "avg_ms": None}
    return info


@tool(
    "battery_status",
    "Niveau de batterie, branchement secteur et autonomie restante estimee.",
    category="systeme",
)
def battery_status() -> str:
    b = psutil.sensors_battery()
    if b is None:
        return "Aucune batterie detectee (PC fixe ?)."
    txt = f"Batterie a {round(b.percent)} %, {'sur secteur' if b.power_plugged else 'sur batterie'}"
    if b.secsleft and b.secsleft > 0 and not b.power_plugged:
        txt += f", environ {_fmt_duration(b.secsleft)} restantes"
    return txt + "."
