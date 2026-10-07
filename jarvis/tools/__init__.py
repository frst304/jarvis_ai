"""Registre des outils que JARVIS peut utiliser pour agir sur le PC et le monde."""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

# Niveaux de risque :
#   safe   -> lecture seule, jamais de confirmation
#   action -> effet benin (ouvrir une appli, taper du texte...), confirmation en mode "prudent"
#   danger -> irreversible / sensible (supprimer, eteindre, shell...), confirmation sauf en mode "total"
RISKS = ("safe", "action", "danger")


@dataclass
class ToolSpec:
    name: str
    description: str
    properties: dict
    required: tuple[str, ...]
    func: Callable[..., Any]
    risk: str = "safe"
    category: str = "general"
    confirm: Callable[[dict], str] | None = None
    wants_ctx: bool = False

    def definition(self, eager: bool = True) -> dict:
        schema = {"type": "object", "properties": self.properties}
        if self.required:
            schema["required"] = list(self.required)
        tool = {"name": self.name, "description": self.description, "input_schema": schema}
        if eager:
            tool["eager_input_streaming"] = True
        return tool

    def risk_for(self, args: dict) -> str:
        return self.risk(args) if callable(self.risk) else self.risk


@dataclass
class ToolResult:
    """Resultat riche : texte + blocs (images) a renvoyer a Claude."""

    text: str
    images: list[dict] = field(default_factory=list)  # [{"media_type":..., "data": b64}]
    hud: dict | None = None

    def content_blocks(self) -> list[dict]:
        blocks: list[dict] = [{"type": "text", "text": self.text}]
        for img in self.images:
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]},
            })
        return blocks


class ToolError(Exception):
    """Erreur lisible renvoyee a Claude (is_error=True)."""


@dataclass
class ToolContext:
    """Acces au coeur de JARVIS pour les outils qui en ont besoin."""

    emit: Callable[[dict], Awaitable[None]]
    confirm: Callable[[str], Awaitable[bool]]
    run_tool: Callable[[str, dict], Awaitable["ToolOutcome"]] | None = None


@dataclass
class ToolOutcome:
    ok: bool
    text: str
    content: list[dict] | str
    hud: dict | None = None


REGISTRY: dict[str, ToolSpec] = {}


def tool(
    name: str,
    description: str,
    properties: dict | None = None,
    required: tuple[str, ...] | list[str] = (),
    risk: str | Callable[[dict], str] = "safe",
    category: str = "general",
    confirm: Callable[[dict], str] | None = None,
):
    def deco(func: Callable[..., Any]):
        wants_ctx = "ctx" in inspect.signature(func).parameters
        REGISTRY[name] = ToolSpec(
            name=name,
            description=description,
            properties=properties or {},
            required=tuple(required),
            func=func,
            risk=risk,
            category=category,
            confirm=confirm,
            wants_ctx=wants_ctx,
        )
        return func

    return deco


_TYPES = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def validate(spec: ToolSpec, args: Any) -> dict:
    """Valide (et normalise) les arguments fournis par le modele. Leve ToolError."""
    if not isinstance(args, dict):
        raise ToolError(f"Arguments invalides pour {spec.name}: un objet JSON est attendu.")
    for key in spec.required:
        if key not in args or args[key] in (None, ""):
            raise ToolError(f"Parametre obligatoire manquant: '{key}'.")
    clean: dict = {}
    for key, value in args.items():
        prop = spec.properties.get(key)
        if prop is None:
            continue  # on ignore les cles inconnues
        expected = prop.get("type")
        if expected == "integer" and isinstance(value, float) and value.is_integer():
            value = int(value)
        if expected == "integer" and isinstance(value, str) and value.strip().lstrip("-").isdigit():
            value = int(value)
        if expected == "number" and isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                pass
        if expected in _TYPES:
            ok = isinstance(value, _TYPES[expected])
            if expected in ("integer", "number") and isinstance(value, bool):
                ok = False
            if not ok:
                raise ToolError(f"Le parametre '{key}' doit etre de type {expected}.")
        if "enum" in prop and value not in prop["enum"]:
            raise ToolError(f"Valeur invalide pour '{key}': {value!r}. Choix: {prop['enum']}.")
        clean[key] = value
    return clean


def _to_outcome(result: Any) -> ToolOutcome:
    if isinstance(result, ToolResult):
        return ToolOutcome(True, result.text, result.content_blocks() if result.images else result.text, result.hud)
    if isinstance(result, (dict, list)):
        text = json.dumps(result, ensure_ascii=False, default=str)
    else:
        text = "OK" if result is None else str(result)
    if len(text) > 60_000:
        text = text[:60_000] + "\n...[resultat tronque]"
    return ToolOutcome(True, text, text)


async def execute(name: str, args: dict, ctx: ToolContext | None = None, timeout: float = 180) -> ToolOutcome:
    """Execute un outil du registre (sans gestion de confirmation)."""
    spec = REGISTRY.get(name)
    if spec is None:
        msg = f"Outil inconnu: {name}"
        return ToolOutcome(False, msg, msg)
    try:
        clean = validate(spec, args)
        kwargs = dict(clean)
        if spec.wants_ctx:
            kwargs["ctx"] = ctx
        if inspect.iscoroutinefunction(spec.func):
            result = await asyncio.wait_for(spec.func(**kwargs), timeout)
        else:
            result = await asyncio.wait_for(asyncio.to_thread(spec.func, **kwargs), timeout)
        return _to_outcome(result)
    except ToolError as exc:
        return ToolOutcome(False, str(exc), str(exc))
    except asyncio.TimeoutError:
        msg = f"L'outil {name} a depasse le delai de {timeout:.0f}s."
        return ToolOutcome(False, msg, msg)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - on renvoie l'erreur a Claude
        msg = f"Erreur pendant {name}: {type(exc).__name__}: {exc}"
        return ToolOutcome(False, msg, msg)


def load_all() -> dict[str, ToolSpec]:
    """Importe tous les modules d'outils (ils s'enregistrent via @tool)."""
    from . import apps, control, files, hud, media, productivity, shell, system, web  # noqa: F401

    return REGISTRY
