"""Outils d'interface : afficher des panneaux holographiques, notifications, changer le theme."""

from __future__ import annotations

from ..config import update_settings
from . import ToolContext, ToolError, tool


@tool(
    "display_on_hud",
    "Affiche un panneau holographique dans l'interface de JARVIS (a cote de la reponse vocale). A utiliser pour "
    "tout contenu detaille : tableaux, listes, code, comparatifs, recettes, itineraires, resultats chiffres, "
    "graphiques. La voix doit alors rester breve et renvoyer au panneau.",
    {
        "title": {"type": "string"},
        "markdown": {"type": "string", "description": "Contenu en Markdown (titres, listes, tableaux, code)."},
        "chart": {
            "type": "object",
            "description": "Graphique optionnel.",
            "properties": {
                "type": {"type": "string", "enum": ["bar", "line", "pie"]},
                "labels": {"type": "array", "items": {"type": "string"}},
                "series": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"name": {"type": "string"},
                                                                "values": {"type": "array", "items": {"type": "number"}}}},
                },
                "unit": {"type": "string"},
            },
        },
        "image_url": {"type": "string", "description": "Image a afficher (URL https)."},
    },
    required=["title"],
    category="interface",
)
async def display_on_hud(title: str, markdown: str = "", chart: dict | None = None, image_url: str = "",
                         ctx: ToolContext | None = None) -> str:
    if not markdown and not chart and not image_url:
        raise ToolError("Fournir 'markdown', 'chart' ou 'image_url'.")
    if image_url and not image_url.startswith("https://"):
        image_url = ""
    if ctx is not None:
        await ctx.emit({"type": "hud_card", "card": {"title": title, "markdown": markdown, "chart": chart,
                                                      "image_url": image_url}})
    return "Panneau affiche."


@tool(
    "send_notification",
    "Envoie une notification bureau (et dans l'interface).",
    {"title": {"type": "string"}, "message": {"type": "string"}},
    required=["message"],
    risk="action",
    category="interface",
)
async def send_notification(message: str, title: str = "JARVIS", ctx: ToolContext | None = None) -> str:
    if ctx is not None:
        await ctx.emit({"type": "toast", "title": title, "message": message})
    try:
        from plyer import notification  # type: ignore

        notification.notify(title=title, message=message[:250], app_name="JARVIS", timeout=8)
    except Exception:  # noqa: BLE001 - la notification dans l'interface suffit
        pass
    return "Notification envoyee."


@tool(
    "change_interface",
    "Modifie l'apparence/le comportement de l'interface : theme (arc = bleu reacteur, mark3 = rouge et or "
    "Iron Man, stealth = sombre discret, vibranium = violet), effets sonores, ecoute du mot d'activation.",
    {
        "theme": {"type": "string", "enum": ["arc", "mark3", "stealth", "vibranium"]},
        "sound_fx": {"type": "boolean"},
        "wake_word_enabled": {"type": "boolean"},
    },
    risk="safe",
    category="interface",
)
async def change_interface(theme: str = "", sound_fx: bool | None = None, wake_word_enabled: bool | None = None,
                           ctx: ToolContext | None = None) -> str:
    changes: dict = {}
    if theme:
        changes["theme"] = theme
    if sound_fx is not None:
        changes["sound_fx"] = sound_fx
    if wake_word_enabled is not None:
        changes["wake_word_enabled"] = wake_word_enabled
    if not changes:
        raise ToolError("Rien a modifier.")
    settings = update_settings(changes)
    if ctx is not None:
        await ctx.emit({"type": "settings", "settings": settings.public()})
    return "Interface mise a jour : " + ", ".join(f"{k}={v}" for k, v in changes.items())
