"""Chargement / sauvegarde des reglages de JARVIS."""

from __future__ import annotations

import json
import os
import platform
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT_DIR / "web"

load_dotenv(ROOT_DIR / ".env")

DATA_DIR = Path(os.environ.get("JARVIS_DATA_DIR") or (ROOT_DIR / "data")).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

PORT = int(os.environ.get("JARVIS_PORT", "8777"))
HOST = "127.0.0.1"

OS_NAME = platform.system()  # "Windows", "Darwin", "Linux"
IS_WINDOWS = OS_NAME == "Windows"
IS_MAC = OS_NAME == "Darwin"
IS_LINUX = OS_NAME == "Linux"

# Modeles proposes dans l'interface. Les capacites conditionnent la requete API.
MODELS: dict[str, dict] = {
    "claude-opus-5-5": {
        "label": "Claude Opus 5.5 - le plus intelligent",
        "effort": True,
        "adaptive_thinking": True,
        "fallbacks": True,
        "computer_use": True,
        "web_search": "web_search_20260209",
        "web_fetch": "web_fetch_20260209",
    },
    "claude-sonnet-5-5": {
        "label": "Claude Sonnet 5.5 - rapide et capable",
        "effort": True,
        "adaptive_thinking": True,
        "fallbacks": True,
        "computer_use": True,
        "web_search": "web_search_20260209",
        "web_fetch": "web_fetch_20260209",
    },
    "claude-haiku-4-5": {
        "label": "Claude Haiku 4.5 - ultra rapide, economique",
        "effort": False,
        "adaptive_thinking": False,
        "fallbacks": False,
        "computer_use": False,
        "web_search": "web_search_20250305",
        "web_fetch": "web_fetch_20250910",
    },
}
DEFAULT_MODEL = "claude-opus-5-5"

# Voix feminines neurales (edge-tts) proposees par defaut.
VOICES = [
    {"id": "fr-FR-DeniseNeural", "label": "Denise (FR) - claire et elegante"},
    {"id": "fr-FR-VivienneMultilingualNeural", "label": "Vivienne (FR) - naturelle, multilingue"},
    {"id": "fr-FR-EloiseNeural", "label": "Eloise (FR) - jeune et vive"},
    {"id": "fr-CA-SylvieNeural", "label": "Sylvie (QC)"},
    {"id": "fr-BE-CharlineNeural", "label": "Charline (BE)"},
    {"id": "fr-CH-ArianeNeural", "label": "Ariane (CH)"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia (UK) - style FRIDAY"},
    {"id": "en-US-AvaMultilingualNeural", "label": "Ava (US) - multilingue"},
    {"id": "en-US-JennyNeural", "label": "Jenny (US)"},
]


@dataclass
class Settings:
    # Identite
    user_name: str = "Monsieur"
    assistant_name: str = "JARVIS"
    language: str = "fr-FR"
    city: str = ""  # vide = detection automatique par IP

    # Cerveau
    api_key: str = ""  # optionnel : sinon ANTHROPIC_API_KEY dans .env
    model: str = DEFAULT_MODEL
    effort: str = "low"  # low | medium | high | xhigh | max
    autonomy: str = "normal"  # prudent | normal | total
    computer_use: bool = True  # autoriser la prise de controle souris/clavier
    web_search: bool = True

    # Voix
    tts_engine: str = "edge"  # edge | browser | off
    voice: str = "fr-FR-DeniseNeural"
    voice_rate: int = 5  # en %
    voice_pitch: int = 0  # en Hz
    voice_fx: bool = True  # effet "holographique" cote navigateur
    wake_word_enabled: bool = False
    wake_word: str = "jarvis"
    continuous_conversation: bool = False

    # Interface
    theme: str = "arc"  # arc | mark3 | stealth | vibranium
    sound_fx: bool = True
    boot_sequence: bool = True
    morning_briefing: bool = False

    extra: dict = field(default_factory=dict)

    def public(self) -> dict:
        """Version envoyee au navigateur (sans la cle API en clair)."""
        data = asdict(self)
        key = self.effective_api_key()
        data["api_key"] = ""
        data["api_key_set"] = bool(key)
        data["api_key_hint"] = (key[:7] + "..." + key[-4:]) if len(key) > 16 else ""
        return data

    def effective_api_key(self) -> str:
        return (self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")).strip()

    def model_caps(self) -> dict:
        return MODELS.get(self.model, MODELS[DEFAULT_MODEL])


_SETTINGS_FILE = DATA_DIR / "settings.json"
_lock = threading.Lock()
_settings: Settings | None = None

_VALID = {
    "effort": {"low", "medium", "high", "xhigh", "max"},
    "autonomy": {"prudent", "normal", "total"},
    "tts_engine": {"edge", "browser", "off"},
    "theme": {"arc", "mark3", "stealth", "vibranium"},
}


def _coerce(name: str, value, current):
    if isinstance(current, bool):
        return bool(value)
    if isinstance(current, int):
        return int(value)
    if isinstance(current, dict):
        return dict(value or {})
    value = str(value)
    if name in _VALID and value not in _VALID[name]:
        raise ValueError(f"Valeur invalide pour {name}: {value}")
    if name == "model" and value not in MODELS:
        raise ValueError(f"Modele inconnu: {value}")
    return value


def get_settings() -> Settings:
    global _settings
    with _lock:
        if _settings is None:
            _settings = Settings()
            if _SETTINGS_FILE.exists():
                try:
                    raw = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
                    _apply(_settings, raw)
                except (OSError, ValueError):
                    pass
        return _settings


def _apply(target: Settings, changes: dict) -> None:
    known = {f.name for f in fields(Settings)}
    for name, value in changes.items():
        if name not in known:
            continue
        if name == "api_key" and not value:
            continue  # une valeur vide ne doit pas effacer la cle enregistree
        try:
            setattr(target, name, _coerce(name, value, getattr(target, name)))
        except (TypeError, ValueError):
            continue


def update_settings(changes: dict) -> Settings:
    settings = get_settings()
    with _lock:
        if changes.get("clear_api_key"):
            settings.api_key = ""
        _apply(settings, changes)
        tmp = _SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_SETTINGS_FILE)
    return settings
