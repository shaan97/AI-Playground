"""Tests for the Ollama/Gemma chat adapter. Deterministic — no live model.

We monkeypatch urllib so no network is touched. Run as
``python v2/tests/test_ollama_adapter.py``.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from gds import PENDING, Step  # noqa: E402
from gds.agents import ollama as O  # noqa: E402

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"ok:   {name}")
    else:
        _FAIL += 1
        print(f"FAIL: {name}  {detail}")


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


def _patch_urlopen(capture, payload=None, raises=None):
    def fake_urlopen(req, timeout=None):
        capture["url"] = req.full_url
        capture["method"] = req.get_method()
        capture["headers"] = dict(req.header_items())
        capture["body"] = json.loads(req.data.decode())
        if raises is not None:
            raise raises
        return _FakeResp(payload)
    return fake_urlopen


def _assistant_with_set_state():
    return {"choices": [{"message": {
        "content": None,
        "tool_calls": [{"id": "c1", "function": {
            "name": "set_state", "arguments": json.dumps({"state": {"mood": "curious"}})}}],
    }}]}


def test_request_shape_and_passthrough():
    capture = {}
    orig = urllib.request.urlopen
    urllib.request.urlopen = _patch_urlopen(capture, payload=_assistant_with_set_state())
    try:
        tools = [{"type": "function", "function": {"name": "set_state", "parameters": {}}}]
        msg = O.ollama_chat([{"role": "user", "content": "hi"}], tools, model="gemma4")
    finally:
        urllib.request.urlopen = orig

    check("adapter hits the OpenAI-compatible chat endpoint",
          capture["url"].endswith("/v1/chat/completions"), capture.get("url", ""))
    check("adapter POSTs", capture["method"] == "POST")
    body = capture["body"]
    check("body carries model/messages/tools, stream off",
          body["model"] == "gemma4" and body["tools"] == tools
          and body["messages"][0]["content"] == "hi" and body["stream"] is False)
    check("body includes Gemma sampling options",
          body["options"]["temperature"] == 1.0 and body["options"]["top_k"] == 64)
    check("returns the assistant message verbatim",
          isinstance(msg, dict) and msg["tool_calls"][0]["function"]["name"] == "set_state")


def test_gemma_agent_factory_drives_kernel():
    capture = {}
    orig = urllib.request.urlopen
    # First call -> set_state; LLMKernel then calls again -> no tool calls (stop).
    payloads = [_assistant_with_set_state(), {"choices": [{"message": {"content": "done"}}]}]

    def fake(req, timeout=None):
        capture["body"] = json.loads(req.data.decode())
        return _FakeResp(payloads.pop(0))

    urllib.request.urlopen = fake
    try:
        agent = O.gemma_agent(model="gemma4")
        result = agent.evaluate({"mood": "old"}, {})
    finally:
        urllib.request.urlopen = orig

    check("gemma_agent returns an LLMKernel that produces a Step",
          isinstance(result, Step))
    check("agent applied the model's set_state",
          isinstance(result, Step) and result.next_state == {"mood": "curious"})


def test_connection_error_becomes_pending():
    orig = urllib.request.urlopen
    urllib.request.urlopen = _patch_urlopen({}, raises=urllib.error.URLError("ollama down"))
    try:
        agent = O.gemma_agent(model="gemma4")
        result = agent.evaluate({"keep": "me"}, {})
    finally:
        urllib.request.urlopen = orig
    check("an unreachable Ollama -> agent holds (PENDING)", result is PENDING)


if __name__ == "__main__":
    test_request_shape_and_passthrough()
    test_gemma_agent_factory_drives_kernel()
    test_connection_error_becomes_pending()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    raise SystemExit(1 if _FAIL else 0)
