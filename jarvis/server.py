"""Serveur web local : interface HUD + WebSocket temps reel."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__, monitor, scheduler, storage, voice
from .brain import core
from .config import MODELS, PORT, VOICES, WEB_DIR, get_settings, update_settings
from .osutils import gui_available
from .tools import REGISTRY

ALLOWED_ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}


def _origin_ok(origin: str | None) -> bool:
    # Bloque les sites web qui tenteraient de piloter JARVIS depuis le navigateur (CSRF / WebSocket hijacking).
    return origin is None or origin in ALLOWED_ORIGINS


@asynccontextmanager
async def lifespan(_app: FastAPI):
    storage.seed_default_routines()
    core.start()
    tasks = [asyncio.create_task(scheduler.reminders_loop(core)), asyncio.create_task(scheduler.telemetry_loop(core))]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="JARVIS", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.method != "GET" and not _origin_ok(request.headers.get("origin")):
        return JSONResponse({"error": "origine refusee"}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/info")
async def info():
    s = get_settings()
    return {
        "version": __version__,
        "settings": s.public(),
        "models": {k: v["label"] for k, v in MODELS.items()},
        "voices": VOICES,
        "tools": len(REGISTRY),
        "gui": gui_available(),
        "identity": monitor.system_identity(),
    }


@app.get("/api/tts")
async def tts(text: str, voice_id: str = ""):
    s = get_settings()
    audio = await voice.synthesize(text[:500], voice_id or s.voice, s.voice_rate, s.voice_pitch)
    if not audio:
        raise HTTPException(503, "Synthese vocale indisponible")
    import base64

    return Response(base64.b64decode(audio), media_type="audio/mpeg")


@app.get("/api/panels")
async def panels():
    return scheduler.panels_payload()


@app.get("/api/weather")
async def weather():
    from .tools import execute

    out = await execute("get_weather", {"days": 4})
    return json.loads(out.text) if out.ok else JSONResponse({"error": out.text}, status_code=502)


@app.get("/api/news")
async def news(topic: str = "une"):
    from .tools import execute

    out = await execute("get_news", {"topic": topic, "count": 12})
    return json.loads(out.text) if out.ok else JSONResponse({"error": out.text}, status_code=502)


@app.post("/api/panels/{kind}/{item_id}")
async def panel_action(kind: str, item_id: str, request: Request):
    body = await request.json()
    coll = {"todos": storage.todos, "reminders": storage.reminders, "notes": storage.notes,
            "memory": storage.memory}.get(kind)
    if coll is None:
        raise HTTPException(404)
    if body.get("action") == "delete":
        coll.remove(item_id)
    elif body.get("action") == "toggle" and kind == "todos":
        item = coll.get(item_id)
        if item:
            coll.update(item_id, done=not item.get("done"))
    await core.broadcast({"type": "panels_changed"})
    return {"ok": True}


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    if not _origin_ok(ws.headers.get("origin")):
        await ws.close(code=4403)
        return
    await ws.accept()
    core.clients.add(ws)
    await ws.send_text(json.dumps({
        "type": "hello",
        "settings": get_settings().public(),
        "state": core.state,
        "history": storage.chatlog.recent(40),
        "gui": gui_available(),
        "tools": len(REGISTRY),
    }, ensure_ascii=False, default=str))
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")
            if kind == "user_message":
                text = str(msg.get("text", "")).strip()
                images = [i for i in msg.get("images", []) if isinstance(i, str)]
                if text or images:
                    await core.handle_user(text or "Analyse cette image.", images)
            elif kind == "stop":
                await core.stop()
            elif kind == "confirm_response":
                core.resolve_confirm(str(msg.get("id")), bool(msg.get("approved")))
            elif kind == "new_session":
                await core.stop()
                core.new_session()
                storage.chatlog.clear()
                await core.broadcast({"type": "session_cleared"})
            elif kind == "settings_update":
                changes = msg.get("changes") or {}
                s = update_settings(changes)
                await core.broadcast({"type": "settings", "settings": s.public()})
            elif kind == "speak":
                core.say(str(msg.get("text", ""))[:600])
            elif kind == "ping":
                await ws.send_text('{"type":"pong"}')
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        core.clients.discard(ws)


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
