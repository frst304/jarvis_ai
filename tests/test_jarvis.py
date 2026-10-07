"""Tests rapides : python -m pytest -q"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

os.environ["JARVIS_DATA_DIR"] = tempfile.mkdtemp(prefix="jarvis-test-")
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from jarvis import brain, voice  # noqa: E402
from jarvis.config import get_settings, update_settings  # noqa: E402
from jarvis.tools import REGISTRY, ToolError, execute, validate  # noqa: E402
from jarvis.tools.shell import safe_eval  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_registry_definitions_are_valid():
    assert len(REGISTRY) >= 40
    for spec in REGISTRY.values():
        d = spec.definition()
        assert d["input_schema"]["type"] == "object"
        assert d["eager_input_streaming"] is True
        for req in spec.required:
            assert req in spec.properties


def test_validate_rejects_bad_input():
    spec = REGISTRY["set_volume"]
    assert validate(spec, {"level": "40"}) == {"level": 40}
    with pytest.raises(ToolError):
        validate(spec, {"level": "fort"})
    with pytest.raises(ToolError):
        validate(REGISTRY["open_url"], {})


def test_calculator():
    assert safe_eval("2^10") == 1024
    assert abs(safe_eval("sqrt(2)*pi") - 4.442882938) < 1e-6
    with pytest.raises(ToolError):
        safe_eval("__import__('os').system('x')")


def test_productivity_tools_roundtrip():
    out = run(execute("todos", {"action": "add", "text": "Acheter du lait"}))
    assert out.ok
    listed = json.loads(run(execute("todos", {"action": "list"})).text)
    assert listed[0]["text"] == "Acheter du lait"
    out = run(execute("reminders", {"action": "add", "message": "the", "in_seconds": 60}))
    assert out.ok and "programme" in out.text


def test_sentence_buffer():
    buf = voice.SentenceBuffer()
    chunks = buf.feed("Bien sur. Voici une phrase assez longue pour etre decoupee correctement. Et la suite")
    assert chunks[0] == "Bien sur."
    assert buf.flush() == ["Et la suite"]
    assert "lien" in voice.clean_for_speech("Voir https://exemple.com **vite**")


def test_offline_mode():
    core = brain.Jarvis()
    assert "Il est" in run(brain.offline.handle("quelle heure est-il", core))
    assert "84" in run(brain.offline.handle("calcule 12 fois 7", core))


# ------------------------------------------------------------- faux client Claude

class FakeStream:
    def __init__(self, message, events):
        self.message, self.events = message, events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        async def gen():
            for e in self.events:
                yield e
        return gen()

    async def get_final_message(self):
        return self.message


class FakeClient:
    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kw):
        self.requests.append(kw)
        return self.script.pop(0)


def text_turn(text):
    msg = NS(content=[NS(type="text", text=text)], stop_reason="end_turn", usage=None)
    events = [NS(type="content_block_start", content_block=NS(type="text")),
              NS(type="content_block_delta", delta=NS(type="text_delta", text=text))]
    return FakeStream(msg, events)


def tool_turn(name, args, toolset=None):
    block = NS(type="tool_use", id="toolu_1", name=name, input=args, toolset_name=toolset)
    return FakeStream(NS(content=[block], stop_reason="tool_use", usage=None),
                      [NS(type="content_block_start", content_block=NS(type="tool_use"))])


def test_claude_loop_runs_tools(monkeypatch):
    update_settings({"api_key": "sk-ant-test", "computer_use": False, "tts_engine": "off"})
    fake = FakeClient([tool_turn("calculate", {"expression": "6*7"}), text_turn("Le resultat est 42.")])
    monkeypatch.setattr(brain.anthropic, "AsyncAnthropic", lambda **kw: fake)
    core = brain.Jarvis()
    events = []

    async def capture(e):
        events.append(e)

    monkeypatch.setattr(core, "broadcast", capture)
    run(core._run_claude("combien font 6 fois 7 ?", []))

    first = fake.requests[0]
    assert first["model"] == get_settings().model
    assert first["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in first["betas"]
    assert any(t.get("type", "").startswith("web_search") for t in first["tools"])
    # le resultat de l'outil est renvoye a Claude
    tool_result = core.history[2]["content"][0]
    assert tool_result["type"] == "tool_result" and "42" in tool_result["content"]
    assert events[-1]["type"] == "assistant_end" and "42" in events[-1]["text"]


def test_danger_tool_requires_confirmation(monkeypatch):
    update_settings({"api_key": "sk-ant-test", "autonomy": "normal", "tts_engine": "off"})
    fake = FakeClient([tool_turn("run_shell_command", {"command": "echo hi"}), text_turn("Annule.")])
    monkeypatch.setattr(brain.anthropic, "AsyncAnthropic", lambda **kw: fake)
    core = brain.Jarvis()

    async def deny(text):
        return False

    async def noop(e):
        return None

    monkeypatch.setattr(core, "confirm", deny)
    monkeypatch.setattr(core, "broadcast", noop)
    run(core._run_claude("lance echo", []))
    result = core.history[2]["content"][0]
    assert result["is_error"] is True and "refusee" in result["content"]


def test_computer_results_echo_toolset(monkeypatch):
    update_settings({"api_key": "sk-ant-test", "autonomy": "normal", "tts_engine": "off"})
    fake = FakeClient([tool_turn("wait", {"duration": 0}, toolset="computer"), text_turn("Fait.")])
    monkeypatch.setattr(brain.anthropic, "AsyncAnthropic", lambda **kw: fake)
    core = brain.Jarvis()

    async def noop(e):
        return None

    monkeypatch.setattr(core, "broadcast", noop)
    run(core._run_claude("attends", []))
    result = core.history[2]["content"][0]
    assert result["toolset_name"] == "computer" and result["content"] == "OK"
