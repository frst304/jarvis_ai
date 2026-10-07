"""Outils de productivite : memoire a long terme, notes, taches, rappels/minuteurs, routines."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from .. import storage
from . import ToolContext, ToolError, tool


async def _refresh(ctx: ToolContext | None) -> None:
    if ctx is not None:
        await ctx.emit({"type": "panels_changed"})


@tool(
    "long_term_memory",
    "Memoire a long terme de JARVIS sur l'utilisateur (preferences, infos personnelles, habitudes, proches...). "
    "Utiliser 'remember' des que l'utilisateur partage une info durable ou demande de retenir quelque chose ; "
    "'search'/'list' pour retrouver ; 'forget' pour oublier.",
    {
        "action": {"type": "string", "enum": ["remember", "forget", "list", "search"]},
        "fact": {"type": "string", "description": "Info a retenir, formulee a la 3e personne (ex: 'Prefere le the au cafe')."},
        "category": {"type": "string", "description": "Ex: preference, personnel, travail, sante, proches."},
        "query": {"type": "string"},
        "id": {"type": "string"},
    },
    required=["action"],
    category="memoire",
)
async def memory(action: str, fact: str = "", category: str = "general", query: str = "", id: str = "",
                 ctx: ToolContext | None = None):
    if action == "remember":
        if not fact:
            raise ToolError("'fact' requis.")
        item = storage.memory.add(fact=fact, category=category or "general")
        await _refresh(ctx)
        return f"Memorise (id {item['id']}) : {fact}"
    if action == "forget":
        target = id
        if not target and (query or fact):
            found = storage.memory.find(query or fact, ("fact",))
            if not found:
                raise ToolError("Aucun souvenir correspondant.")
            target = found[0]["id"]
        if not storage.memory.remove(target):
            raise ToolError("Souvenir introuvable.")
        await _refresh(ctx)
        return "Souvenir efface."
    items = storage.memory.find(query, ("fact", "category")) if action == "search" and query else storage.memory.all()
    return [{"id": i["id"], "fact": i["fact"], "category": i.get("category")} for i in items] or "Aucun souvenir."


@tool(
    "notes",
    "Bloc-notes de JARVIS : prendre une note (dictee, idee, liste de courses...), lister, lire, chercher, supprimer.",
    {
        "action": {"type": "string", "enum": ["add", "list", "read", "search", "delete", "append"]},
        "title": {"type": "string"},
        "content": {"type": "string"},
        "query": {"type": "string"},
        "id": {"type": "string"},
    },
    required=["action"],
    category="productivite",
)
async def notes(action: str, title: str = "", content: str = "", query: str = "", id: str = "",
                ctx: ToolContext | None = None):
    if action == "add":
        if not content and not title:
            raise ToolError("Contenu requis.")
        item = storage.notes.add(title=title or content[:40], content=content)
        await _refresh(ctx)
        return f"Note enregistree (id {item['id']}) : {item['title']}"
    if action in ("read", "delete", "append"):
        target = storage.notes.get(id) if id else None
        if target is None and (query or title):
            found = storage.notes.find(query or title, ("title", "content"))
            target = found[0] if found else None
        if target is None:
            raise ToolError("Note introuvable.")
        if action == "read":
            return target
        if action == "append":
            storage.notes.update(target["id"], content=(target.get("content", "") + "\n" + content).strip())
            await _refresh(ctx)
            return f"Note « {target['title']} » completee."
        storage.notes.remove(target["id"])
        await _refresh(ctx)
        return f"Note « {target['title']} » supprimee."
    items = storage.notes.find(query, ("title", "content")) if action == "search" and query else storage.notes.all()
    return [{"id": n["id"], "title": n["title"], "content": n.get("content", "")[:300],
             "date": datetime.fromtimestamp(n["created"]).strftime("%d/%m/%Y %H:%M")} for n in items] or "Aucune note."


@tool(
    "todos",
    "Liste de taches : ajouter (avec echeance et priorite optionnelles), lister, cocher/decocher, supprimer, "
    "nettoyer les taches terminees.",
    {
        "action": {"type": "string", "enum": ["add", "list", "complete", "uncomplete", "delete", "clear_done"]},
        "text": {"type": "string"},
        "due": {"type": "string", "description": "Echeance libre ou ISO, ex: '2026-10-12' ou 'vendredi'."},
        "priority": {"type": "string", "enum": ["basse", "normale", "haute"]},
        "id": {"type": "string", "description": "Identifiant (ou utiliser 'text' pour retrouver la tache)."},
    },
    required=["action"],
    category="productivite",
)
async def todos(action: str, text: str = "", due: str = "", priority: str = "normale", id: str = "",
                ctx: ToolContext | None = None):
    if action == "add":
        if not text:
            raise ToolError("'text' requis.")
        item = storage.todos.add(text=text, due=due, priority=priority, done=False)
        await _refresh(ctx)
        return f"Tache ajoutee (id {item['id']}) : {text}"
    if action == "clear_done":
        n = 0
        for t in storage.todos.all():
            if t.get("done"):
                storage.todos.remove(t["id"])
                n += 1
        await _refresh(ctx)
        return f"{n} tache(s) terminee(s) supprimee(s)."
    if action in ("complete", "uncomplete", "delete"):
        target = id
        if not target and text:
            found = storage.todos.find(text, ("text",))
            target = found[0]["id"] if found else ""
        if not target:
            raise ToolError("Tache introuvable.")
        ok = storage.todos.remove(target) if action == "delete" else storage.todos.update(target, done=action == "complete")
        if not ok:
            raise ToolError("Tache introuvable.")
        await _refresh(ctx)
        return {"complete": "Tache terminee.", "uncomplete": "Tache rouverte.", "delete": "Tache supprimee."}[action]
    items = storage.todos.all()
    order = {"haute": 0, "normale": 1, "basse": 2}
    items.sort(key=lambda t: (t.get("done", False), order.get(t.get("priority", "normale"), 1), t["created"]))
    return [{"id": t["id"], "text": t["text"], "done": t.get("done", False), "due": t.get("due", ""),
             "priority": t.get("priority", "normale")} for t in items] or "Aucune tache."


def parse_when(at: str = "", in_seconds: float | None = None) -> float:
    now = time.time()
    if in_seconds is not None and in_seconds > 0:
        return now + float(in_seconds)
    if not at:
        raise ToolError("Indiquer 'in_seconds' ou 'at'.")
    at = at.strip().replace("h", ":") if len(at) <= 5 else at.strip()
    if len(at) <= 5 and ":" in at:
        hh, mm = at.split(":", 1)
        target = datetime.now().replace(hour=int(hh), minute=int(mm or 0), second=0, microsecond=0)
        if target.timestamp() <= now:
            target += timedelta(days=1)
        return target.timestamp()
    try:
        dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolError("Format de date invalide (utiliser ISO 8601, ex: 2026-10-08T09:00).") from exc
    return dt.timestamp()


@tool(
    "reminders",
    "Rappels et minuteurs : JARVIS previent l'utilisateur a voix haute + notification au moment voulu. "
    "Utiliser 'in_seconds' pour un delai (minuteur, 'dans 10 minutes' = 600) ou 'at' pour une heure precise "
    "(ISO 8601 ou 'HH:MM'). Repetition possible (quotidienne, hebdomadaire, horaire).",
    {
        "action": {"type": "string", "enum": ["add", "list", "cancel"]},
        "message": {"type": "string", "description": "Ce qu'il faudra rappeler."},
        "in_seconds": {"type": "number"},
        "at": {"type": "string"},
        "repeat": {"type": "string", "enum": ["none", "hourly", "daily", "weekly"]},
        "kind": {"type": "string", "enum": ["reminder", "timer"]},
        "id": {"type": "string"},
    },
    required=["action"],
    category="productivite",
)
async def reminders(action: str, message: str = "", in_seconds: float | None = None, at: str = "",
                    repeat: str = "none", kind: str = "reminder", id: str = "", ctx: ToolContext | None = None):
    if action == "add":
        due = parse_when(at, in_seconds)
        item = storage.reminders.add(message=message or ("Minuteur termine" if kind == "timer" else "Rappel"),
                                     due=due, repeat=repeat, kind=kind, fired=False)
        await _refresh(ctx)
        when = datetime.fromtimestamp(due).strftime("%d/%m a %H:%M:%S")
        return f"{'Minuteur' if kind == 'timer' else 'Rappel'} programme pour le {when} (id {item['id']})."
    if action == "cancel":
        target = id
        if not target and message:
            found = storage.reminders.find(message, ("message",))
            target = found[0]["id"] if found else ""
        if not target or not storage.reminders.remove(target):
            raise ToolError("Rappel introuvable.")
        await _refresh(ctx)
        return "Rappel annule."
    items = [r for r in storage.reminders.all() if not r.get("fired")]
    items.sort(key=lambda r: r["due"])
    return [{"id": r["id"], "message": r["message"], "kind": r.get("kind"), "repeat": r.get("repeat"),
             "quand": datetime.fromtimestamp(r["due"]).strftime("%d/%m %H:%M:%S"),
             "dans_minutes": round((r["due"] - time.time()) / 60, 1)} for r in items] or "Aucun rappel en attente."


@tool(
    "routines",
    "Routines / macros : sequences d'actions declenchees par un nom (ex: 'travail', 'detente', 'depart'). "
    "Lister, executer, creer (steps = liste de {tool, args} avec les noms d'outils de JARVIS), supprimer.",
    {
        "action": {"type": "string", "enum": ["list", "run", "create", "delete"]},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {"type": "object", "properties": {"tool": {"type": "string"}, "args": {"type": "object"}},
                      "required": ["tool"]},
        },
    },
    required=["action"],
    risk=lambda a: "action" if a.get("action") in ("run", "create", "delete") else "safe",
    category="automatisation",
)
async def routines(action: str, name: str = "", description: str = "", steps: list | None = None,
                   ctx: ToolContext | None = None):
    from . import REGISTRY

    if action == "list":
        return [{"name": r["name"], "description": r.get("description", ""),
                 "steps": [s.get("tool") for s in r.get("steps", [])]} for r in storage.routines.all()] or "Aucune routine."
    found = [r for r in storage.routines.all() if r["name"].lower() == name.lower().strip()]
    if action == "create":
        if not name or not steps:
            raise ToolError("'name' et 'steps' requis.")
        unknown = [s.get("tool") for s in steps if s.get("tool") not in REGISTRY or s.get("tool") == "routines"]
        if unknown:
            raise ToolError(f"Outils inconnus ou interdits dans une routine : {unknown}")
        for r in found:
            storage.routines.remove(r["id"])
        storage.routines.add(name=name.lower().strip(), description=description, steps=steps)
        return f"Routine « {name} » enregistree ({len(steps)} etapes)."
    if not found:
        raise ToolError(f"Routine « {name} » introuvable.")
    if action == "delete":
        storage.routines.remove(found[0]["id"])
        return f"Routine « {name} » supprimee."
    if ctx is None or ctx.run_tool is None:
        raise ToolError("Execution de routine indisponible.")
    report = []
    for step in found[0].get("steps", []):
        tname = step.get("tool")
        if tname == "routines":
            continue
        outcome = await ctx.run_tool(tname, step.get("args") or {})
        report.append(f"{'OK' if outcome.ok else 'ECHEC'} {tname}: {outcome.text[:200]}")
    return f"Routine « {name} » executee :\n" + "\n".join(report)
