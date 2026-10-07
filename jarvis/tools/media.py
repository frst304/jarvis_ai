"""Outil multimedia : lecture/pause, piste suivante/precedente via les touches media."""

from __future__ import annotations

from ..osutils import gui
from . import ToolError, tool

_KEYS = {
    "play_pause": "playpause", "pause": "playpause", "play": "playpause", "next": "nexttrack",
    "previous": "prevtrack", "stop": "stop", "volume_up": "volumeup", "volume_down": "volumedown", "mute": "volumemute",
}


@tool(
    "media_control",
    "Controle la lecture multimedia en cours (Spotify, YouTube, VLC, Deezer...) : lecture/pause, piste suivante, "
    "precedente, stop, volume +/-, muet.",
    {
        "action": {"type": "string", "enum": list(_KEYS)},
        "times": {"type": "integer", "description": "Nombre d'appuis (ex: volume_up x5)."},
    },
    required=["action"],
    risk="action",
    category="media",
)
def media_control(action: str, times: int = 1) -> str:
    try:
        gui().press(_KEYS[action], presses=max(1, min(int(times or 1), 50)))
    except RuntimeError as exc:
        raise ToolError(str(exc)) from exc
    return f"Commande media « {action} » envoyee."
