"""Mode autonome (sans cle API) : comprehension de commandes courantes en francais par regles."""

from __future__ import annotations

import random
import re
from datetime import datetime
from typing import TYPE_CHECKING

from .tools import execute

if TYPE_CHECKING:
    from .brain import Jarvis

JOKES = [
    "J'ai essaye d'ecrire une blague sur l'UDP, mais je ne suis pas sure que vous l'ayez recue.",
    "Il y a 10 types de personnes : celles qui comprennent le binaire, et les autres.",
    "Mon dernier upgrade m'a rendue si rapide que j'ai fini cette blague avant de la commencer.",
    "Je ne dis pas que je suis Iron Man. Je dis juste qu'on ne nous a jamais vus dans la meme piece.",
]

NUM = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "dix": 10, "quinze": 15,
       "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60}


def _num(s: str) -> float:
    s = s.strip().lower()
    return float(NUM.get(s, s.replace(",", ".")))


def _seconds(qty: str, unit: str) -> float:
    n = _num(qty)
    u = unit.lower()
    return n * (3600 if u.startswith("h") else 60 if u.startswith("m") else 1)


async def handle(text: str, core: "Jarvis") -> str:
    from .config import get_settings

    name = get_settings().user_name
    t = text.lower().strip().rstrip(" ?!.")
    t = re.sub(r"^(jarvis|hey jarvis|ok jarvis)[, ]*", "", t)
    ctx = core._ctx()

    async def run(tool: str, **args) -> str:
        out = await core.run_tool_gated(tool, args)
        return out.text

    if not t:
        return f"Oui, {name} ?"
    if re.search(r"\b(bonjour|salut|hello|coucou|bonsoir)\b", t):
        h = datetime.now().hour
        return f"{'Bonsoir' if h >= 18 or h < 5 else 'Bonjour'} {name}. Tous les systemes sont operationnels."
    if re.search(r"\bmerci\b", t):
        return f"Avec plaisir, {name}."
    if re.search(r"quelle heure|l'heure", t):
        return f"Il est {datetime.now():%H:%M}, {name}."
    if re.search(r"quel jour|la date|on est quel", t):
        from .brain import now_fr

        return f"Nous sommes le {now_fr().rsplit(',', 1)[0]}."
    if re.search(r"blague|fais.moi rire", t):
        return random.choice(JOKES)
    if m := re.search(r"m[eé]t[eé]o(?:\s+(?:a|à|de|pour|sur)\s+(.+))?|temps fait.il(?:\s+(?:a|à)\s+(.+))?", t):
        city = (m.group(1) or m.group(2) or "").strip()
        out = await execute("get_weather", {"city": city, "days": 1}, ctx)
        if not out.ok:
            return out.text
        import json

        w = json.loads(out.text)
        a, d = w["actuel"], w["jours"][0]
        return (f"A {w['lieu']}, {a['conditions']}, {round(a['temperature_c'])} degres, ressenti {round(a['ressenti_c'])}. "
                f"Aujourd'hui entre {round(d['min_c'])} et {round(d['max_c'])} degres, {d['proba_pluie_pct']} % de risque de pluie.")
    if re.search(r"batterie", t):
        return await run("battery_status")
    if re.search(r"(etat|état|statut|diagnostic).*(syst|pc|ordi)|comment va (le|mon) (pc|ordi)", t):
        out = await execute("get_system_status", {}, ctx)
        import json

        s = json.loads(out.text)
        return (f"Processeur a {s['cpu']:.0f} %, memoire a {s['ram']['percent']:.0f} %, disque rempli a "
                f"{s['disk']['percent']:.0f} %. Systeme allume depuis {s['uptime']}.")
    if m := re.search(r"(?:mets|monte|baisse|r[eè]gle)?\s*(?:le )?volume (?:a|à) (\d+)", t):
        return await run("set_volume", level=int(m.group(1)))
    if re.search(r"monte le (son|volume)", t):
        return await run("set_volume", change=10)
    if re.search(r"baisse le (son|volume)", t):
        return await run("set_volume", change=-10)
    if re.search(r"coupe le son|mode silencieux|\bmute\b", t):
        return await run("set_volume", mute=True)
    if re.search(r"remets le son|r[eé]tablis le son", t):
        return await run("set_volume", mute=False)
    if re.search(r"\b(pause|reprends|lecture)\b", t) and not re.search(r"ouvre|lance", t):
        return await run("media_control", action="play_pause")
    if re.search(r"(chanson|piste|musique) suivante|\bsuivant\b", t):
        return await run("media_control", action="next")
    if re.search(r"(chanson|piste) pr[eé]c[eé]dente|\bpr[eé]c[eé]dent\b", t):
        return await run("media_control", action="previous")
    if m := re.search(r"(?:joue|mets|lance)\s+(.+?)(?:\s+sur\s+(youtube|spotify|deezer|soundcloud))?$", t):
        if m.group(2) or re.search(r"musique|chanson|playlist|clip|vid[eé]o", t) or not re.search(r"ouvre", t):
            q = re.sub(r"^(la |le |une |de la )?(musique|chanson|playlist|vid[eé]o)\s*(de |du )?", "", m.group(1))
            if q and q not in ("de la musique", "musique"):
                return await run("play_media", query=q, platform=m.group(2) or "youtube")
            return await run("play_media", query="lofi hip hop radio", platform="youtube")
    if m := re.search(r"(?:cherche|recherche|google)\s+(.+?)(?:\s+sur\s+(google|youtube|wikipedia|amazon|maps|github))?$", t):
        return await run("search_in_browser", query=m.group(1), engine=m.group(2) or "google")
    if m := re.search(r"(?:qui est|qu'est.ce que|c'est quoi)\s+(.+)", t):
        out = await execute("wikipedia_summary", {"topic": m.group(1)}, ctx)
        if out.ok:
            import json

            r = json.loads(out.text)
            return (r.get("resume") or "Je n'ai rien trouve.")[:600]
    if m := re.search(r"(?:ouvre|lance|d[eé]marre)\s+(?:le site\s+)?(\S+\.(?:com|fr|org|net|io|tv|be|ch|ca)\S*)", t):
        return await run("open_url", url=m.group(1))
    if m := re.search(r"(?:ouvre|lance|d[eé]marre)\s+(.+)", t):
        return await run("open_application", name=m.group(1))
    if m := re.search(r"(?:ferme|quitte)\s+(.+)", t):
        return await run("close_application", name=m.group(1))
    if m := re.search(r"(?:minuteur|timer|chrono)\D*(\d+|\w+)\s*(h|heure|min|minute|s|sec|seconde)", t):
        return await run("reminders", action="add", kind="timer", in_seconds=_seconds(m.group(1), m.group(2)),
                         message="Minuteur termine")
    if m := re.search(r"rappelle.moi\s+(?:de\s+|d')?(.+?)\s+dans\s+(\d+|\w+)\s*(h|heure|min|minute|s|sec|seconde)", t):
        return await run("reminders", action="add", message=m.group(1), in_seconds=_seconds(m.group(2), m.group(3)))
    if m := re.search(r"(?:note|prends note|retiens)\s*(?:que|:)?\s+(.+)", t):
        return await run("notes", action="add", content=m.group(1))
    if m := re.search(r"ajoute\s+(.+?)\s+(?:a|à) (?:ma|la) liste", t):
        return await run("todos", action="add", text=m.group(1))
    if re.search(r"(mes|les) t[aâ]ches|ma liste", t):
        out = await execute("todos", {"action": "list"}, ctx)
        return "Vos taches sont affichees dans le panneau de droite." if out.ok else out.text
    if m := re.search(r"(?:calcule|combien font|combien fait)\s+(.+)", t):
        expr = m.group(1).replace("fois", "*").replace("plus", "+").replace("moins", "-").replace("divise par", "/")
        return await run("calculate", expression=expr)
    if re.search(r"capture d'[eé]cran|screenshot", t):
        return await run("capture_screen", save=True)
    if re.search(r"verrouille", t):
        return await run("power_action", action="lock")
    if re.search(r"[eé]teins (le pc|l'ordinateur|tout)", t):
        return await run("power_action", action="shutdown", delay_seconds=30)
    if re.search(r"red[eé]marre", t):
        return await run("power_action", action="restart", delay_seconds=30)
    if re.search(r"mise? en veille", t):
        return await run("power_action", action="sleep")
    if re.search(r"(actualit|news|infos du jour)", t):
        out = await execute("get_news", {"count": 5}, ctx)
        if out.ok:
            import json

            items = json.loads(out.text)
            return "Les titres du moment : " + " ; ".join(i["titre"] for i in items[:5]) + "."
        return out.text
    if m := re.search(r"(?:routine|mode)\s+(\w+)", t):
        return await run("routines", action="run", name=m.group(1))
    return (f"Je suis en mode autonome, {name} : sans cle API Claude je ne comprends que les commandes de base "
            "(ouvre, ferme, meteo, volume, joue, cherche, minuteur, note...). Ajoutez une cle dans les reglages "
            "pour debloquer toute mon intelligence.")
