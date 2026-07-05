"""Ollama / Gemma 4 chat adapter for `LLMKernel`.

Deliberately minimal and predictable: POST the conversation plus the tool specs
to Ollama's OpenAI-compatible chat endpoint and return the assistant message
**unchanged**. We rely on Gemma 4's native tool calling (needs Ollama >= 0.22.0);
if a turn yields no tool calls, `LLMKernel` simply makes no change that step. No
output massaging, no fallbacks — failures surface as they are.

    from gds.agents.ollama import gemma_agent
    agent = gemma_agent(model="gemma4")          # an LLMKernel; use as any vertex

Stdlib-only (urllib). Requires a running Ollama with the model pulled
(`ollama pull gemma4`).
"""

from __future__ import annotations

import json
import urllib.request
from functools import partial

from .llm import LLMKernel

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma4"

# Google's recommended sampling for Gemma 4 (plain config, override as you like).
DEFAULT_OPTIONS = {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "repeat_penalty": 1.1}


def ollama_chat(
    messages: list[dict],
    tools: list[dict],
    *,
    model: str = DEFAULT_MODEL,
    url: str = DEFAULT_URL,
    options: dict | None = None,
    timeout: float = 300.0,
) -> dict:
    """One model call. Returns the assistant message
    (``{"content": ..., "tool_calls": [...]}``) exactly as Ollama returns it.

    Raises on transport errors — `LLMKernel` turns that into PENDING (the agent
    holds its state that step), which is the desired, predictable behaviour.
    """
    body = json.dumps({
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
        "options": options if options is not None else DEFAULT_OPTIONS,
    }).encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]


def gemma_agent(
    *,
    model: str = DEFAULT_MODEL,
    url: str = DEFAULT_URL,
    system: str | None = None,
    max_rounds: int = 6,
    tools: dict | None = None,
    options: dict | None = None,
    continuous: bool = True,
) -> LLMKernel:
    """Build an `LLMKernel` (a vertex) backed by a local Gemma 4 via Ollama.

    ``continuous`` (default True) keeps one running conversation across steps; pass
    False for the substrate's fresh-conversation-per-step behaviour. See `LLMKernel`.
    """
    chat = partial(ollama_chat, model=model, url=url, options=options)
    return LLMKernel(chat, system=system, max_rounds=max_rounds, tools=tools,
                     continuous=continuous)
