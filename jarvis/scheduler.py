"""Boucles de fond : rappels/minuteurs et telemetrie du tableau de bord."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

from . import monitor, storage
from .config import get_settings

REPEAT = {"hourly": 3600, "daily": 86400, "weekly": 7 * 86400}


async def reminders_loop(core) -> None:
    while True:
        await asyncio.sleep(1)
        now = time.time()
        for r in storage.reminders.all():
            if r.get("fired") or r["due"] > now:
                continue
            step = REPEAT.get(r.get("repeat") or "none")
            if step:
                nxt = r["due"]
                while nxt <= now:
                    nxt += step
                storage.reminders.update(r["id"], due=nxt)
            else:
                storage.reminders.remove(r["id"])
            name = get_settings().user_name
            if r.get("kind") == "timer":
                text = f"{name}, votre minuteur est termine : {r['message']}."
            else:
                text = f"{name}, je vous rappelle : {r['message']}."
            await core.broadcast({"type": "alarm", "kind": r.get("kind", "reminder")})
            await core.announce(text, "Rappel" if r.get("kind") != "timer" else "Minuteur")
            await core.broadcast({"type": "panels_changed"})


async def telemetry_loop(core) -> None:
    tick = 0
    while True:
        await asyncio.sleep(2)
        if not core.clients:
            continue
        tick += 1
        try:
            snap = await asyncio.to_thread(monitor.snapshot, tick % 3 == 0)
        except Exception:  # noqa: BLE001
            continue
        await core.broadcast({"type": "stats", "data": snap})


def panels_payload() -> dict:
    now = time.time()
    rem = sorted((r for r in storage.reminders.all() if not r.get("fired")), key=lambda r: r["due"])
    return {
        "todos": storage.todos.all(),
        "reminders": [{**r, "in_s": r["due"] - now,
                       "when": datetime.fromtimestamp(r["due"]).strftime("%d/%m %H:%M")} for r in rem],
        "notes": sorted(storage.notes.all(), key=lambda n: -n["created"])[:20],
        "memory": storage.memory.all(),
        "routines": [{"name": r["name"], "description": r.get("description", "")} for r in storage.routines.all()],
    }
