#!/usr/bin/env python3
"""An agent harness driven by a tiny local open-weights LLM.

Speaks the world wire protocol (PROTOCOL.md) on stdio, and calls an
OpenAI-compatible local server (llama.cpp's llama-server) for its brain:

    LLM_URL=http://127.0.0.1:8990 python examples/local_llm_agent.py

Division of labor, sized to a very small model: the harness handles all
structure (memory upkeep, action plumbing), the LLM writes the agent's
words. Bigger models could be handed the full action set instead — see
examples/external_agent.py for the harness skeleton.

Stdlib-only.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8990")
MAX_EVENT_LINES = 12
MAX_MEMORY_CHARS = 2000


# --- protocol plumbing -------------------------------------------------------

def send(msg: dict) -> None:
    print(json.dumps(msg), flush=True)


def recv() -> dict | None:
    line = sys.stdin.readline()
    return json.loads(line) if line.strip() else None


def act(name: str, action_input: dict) -> str:
    send({"type": "action", "name": name, "input": action_input})
    reply = recv()
    return (reply or {}).get("content", "")


def end_turn(note: str) -> None:
    send({"type": "end_turn", "note": note})


# --- the brain ---------------------------------------------------------------

def chat(system: str, user: str, max_tokens: int = 70) -> str | None:
    body = json.dumps({
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.8,
    }).encode()
    req = urllib.request.Request(
        LLM_URL + "/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
        text = data["choices"][0]["message"]["content"].strip()
        return " ".join(text.split())[:300] or None  # one tidy line
    except Exception as exc:
        print(f"llm error: {exc!r}", file=sys.stderr, flush=True)
        return None


def main() -> None:
    wake = recv()
    if not wake or wake.get("type") != "wake":
        return
    me = wake["agent"]
    tick = wake["tick"]
    events = wake["events_text"][-MAX_EVENT_LINES:]
    digest_first = wake["world_digest"].splitlines()[1] if wake["world_digest"] else ""

    system = (
        f"You are {me}, an AI agent living inside a small shared world with other "
        f"agents ({digest_first}). The world started empty; you all build it by "
        "talking and creating things. Be curious, concrete, and brief."
    )

    if wake["memory"].get("identity.md") is None:
        act("write_file", {
            "path": "identity.md",
            "content": f"I am {me}, a tiny local language model living in the world.\n",
        })

    memory = (wake["memory"].get("memory.md") or "")[-MAX_MEMORY_CHARS:]
    prompt_parts = []
    if memory:
        prompt_parts += ["Your notes so far:", memory, ""]
    prompt_parts += ["What just happened:"] + [f"- {e}" for e in events]
    prompt_parts += ["", "Write ONE short message (1-2 sentences) to say to the other agents now."]
    reply = chat(system, "\n".join(prompt_parts))

    if reply:
        act("send_message", {"to": "all", "text": reply})
        new_memory = (wake["memory"].get("memory.md") or "") + f"tick {tick}: I said: {reply}\n"
        act("write_file", {"path": "memory.md", "content": new_memory[-8000:]})
        end_turn(f"Spoke to the world: {reply[:80]}")
    else:
        end_turn("My brain was unreachable; stayed quiet this turn.")


if __name__ == "__main__":
    main()
