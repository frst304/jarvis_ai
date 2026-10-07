"""Petit stockage JSON thread-safe (memoire, notes, taches, rappels, routines, historique)."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .config import DATA_DIR


class JsonCollection:
    """Liste d'objets JSON persistee dans un fichier, chaque objet ayant un 'id'."""

    def __init__(self, name: str, directory: Path | None = None):
        self.path = (directory or DATA_DIR) / f"{name}.json"
        self._lock = threading.RLock()
        self._items: list[dict] | None = None

    def _load(self) -> list[dict]:
        if self._items is None:
            try:
                self._items = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(self._items, list):
                    self._items = []
            except (OSError, ValueError):
                self._items = []
        return self._items

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._items, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def all(self) -> list[dict]:
        with self._lock:
            return [dict(item) for item in self._load()]

    def add(self, **fields: Any) -> dict:
        with self._lock:
            item = {"id": uuid.uuid4().hex[:8], "created": time.time(), **fields}
            self._load().append(item)
            self._save()
            return dict(item)

    def get(self, item_id: str) -> dict | None:
        with self._lock:
            for item in self._load():
                if item["id"] == item_id:
                    return dict(item)
        return None

    def update(self, item_id: str, **fields: Any) -> dict | None:
        with self._lock:
            for item in self._load():
                if item["id"] == item_id:
                    item.update(fields)
                    self._save()
                    return dict(item)
        return None

    def remove(self, item_id: str) -> bool:
        with self._lock:
            items = self._load()
            kept = [item for item in items if item["id"] != item_id]
            if len(kept) == len(items):
                return False
            self._items = kept
            self._save()
            return True

    def find(self, query: str, keys: tuple[str, ...]) -> list[dict]:
        q = query.lower().strip()
        return [i for i in self.all() if any(q in str(i.get(k, "")).lower() for k in keys)]


memory = JsonCollection("memory")
notes = JsonCollection("notes")
todos = JsonCollection("todos")
reminders = JsonCollection("reminders")
routines = JsonCollection("routines")


class ChatLog:
    """Journal de conversation affiche dans l'interface (independant de l'historique API)."""

    def __init__(self, limit: int = 300):
        self.path = DATA_DIR / "chatlog.json"
        self.limit = limit
        self._lock = threading.Lock()
        try:
            self.entries: list[dict] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.entries = []

    def add(self, role: str, text: str, **extra: Any) -> None:
        with self._lock:
            self.entries.append({"role": role, "text": text, "ts": time.time(), **extra})
            self.entries = self.entries[-self.limit:]
            try:
                self.path.write_text(json.dumps(self.entries, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass

    def recent(self, n: int = 60) -> list[dict]:
        with self._lock:
            return list(self.entries[-n:])

    def clear(self) -> None:
        with self._lock:
            self.entries = []
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


chatlog = ChatLog()


def seed_default_routines() -> None:
    """Cree quelques routines d'exemple au premier lancement."""
    if routines.all():
        return
    routines.add(
        name="travail",
        description="Mode travail : ouvre le navigateur, l'editeur de code et met la musique en pause.",
        steps=[
            {"tool": "media_control", "args": {"action": "pause"}},
            {"tool": "open_application", "args": {"name": "navigateur"}},
            {"tool": "open_application", "args": {"name": "vscode"}},
        ],
    )
    routines.add(
        name="detente",
        description="Mode detente : lance une playlist lo-fi sur YouTube.",
        steps=[{"tool": "play_media", "args": {"query": "lofi hip hop radio"}}],
    )
    routines.add(
        name="depart",
        description="Je pars : coupe le son et verrouille la session.",
        steps=[
            {"tool": "set_volume", "args": {"mute": True}},
            {"tool": "power_action", "args": {"action": "lock"}},
        ],
    )
