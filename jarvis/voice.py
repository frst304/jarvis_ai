"""Synthese vocale neurale (voix feminine) via edge-tts."""

from __future__ import annotations

import base64
import re

try:
    import edge_tts  # type: ignore
except ImportError:  # pragma: no cover
    edge_tts = None


def clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " (voir le code a l'ecran) ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "le lien affiche", text)
    text = re.sub(r"^\s*\|.*\|\s*$", "", text, flags=re.M)
    text = re.sub(r"[*_#>~]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


_SENTENCE_END = re.compile(r"(?<=[.!?…:;])\s+|\n{2,}")


class SentenceBuffer:
    """Decoupe le flux de texte en phrases pretes a etre prononcees."""

    def __init__(self, min_len: int = 40):
        self.buf = ""
        self.min_len = min_len
        self.first = True

    def feed(self, delta: str) -> list[str]:
        self.buf += delta
        out = []
        while True:
            start = 8 if self.first else self.min_len  # premiere phrase courte = reponse vocale plus rapide
            m = _SENTENCE_END.search(self.buf, min(start, len(self.buf)))
            if m:
                self.first = False
            if not m:
                break
            chunk, self.buf = self.buf[: m.start()], self.buf[m.end():]
            if chunk.count("```") % 2 == 1:  # bloc de code ouvert : on attend la fin
                self.buf = chunk + m.group(0) + self.buf
                break
            if chunk.strip():
                out.append(chunk)
        return out

    def flush(self) -> list[str]:
        rest, self.buf = self.buf, ""
        return [rest] if rest.strip() else []


async def synthesize(text: str, voice: str, rate: int = 0, pitch: int = 0) -> str | None:
    """Renvoie un MP3 encode en base64, ou None si indisponible."""
    text = clean_for_speech(text)
    if not text or edge_tts is None:
        return None
    try:
        comm = edge_tts.Communicate(text, voice, rate=f"{rate:+d}%", pitch=f"{pitch:+d}Hz")
        audio = bytearray()
        async for chunk in comm.stream():
            if chunk.get("type") == "audio":
                audio.extend(chunk["data"])
        return base64.b64encode(bytes(audio)).decode("ascii") if audio else None
    except Exception:  # noqa: BLE001 - hors ligne : le navigateur prendra le relais
        return None
