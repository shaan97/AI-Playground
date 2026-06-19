#!/usr/bin/env python3
"""A real-LLM reference agent backed by Ollama (or any OpenAI-compatible server).

This is the canonical example of an *opaque client*: the world sees only the
seven world operations it calls; everything else — the model, the prompt, its
private memory (local files), and an optional real bash shell (a Docker
container) — lives here, on this machine, invisible to the world.

Built on the thin client (client.py): it registers itself, consumes the SSE
event stream, and acts. No paid API key needed.

    OLLAMA_MODEL=gemma4 python examples/ollama_agent.py --server http://127.0.0.1:8470

With a Docker bash sandbox (see docker/):
    SANDBOX_CONTAINER=agent-sandbox OLLAMA_MODEL=gemma4 \\
        python examples/ollama_agent.py --server http://127.0.0.1:8470

Env vars:
    OLLAMA_URL          Ollama base URL (default: http://127.0.0.1:11434)
    OLLAMA_MODEL        model name (default: gemma4)
    SANDBOX_CONTAINER   Docker container for bash_exec (empty = disabled)
    MAX_ITERATIONS      max tool-call rounds per turn (default: 20)
    BASH_TIMEOUT        seconds before a bash command is killed (default: 30)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from client import WorldClient  # noqa: E402

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4")
SANDBOX_CONTAINER = os.environ.get("SANDBOX_CONTAINER", "")
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "20"))
BASH_TIMEOUT = int(os.environ.get("BASH_TIMEOUT", "30"))
MAX_BASH_OUTPUT = 4000


def log(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


# --------------------------------------------------------------- local tools

# The agent's filesystem is its own — these operate on a local directory and
# never touch the world. They ARE the agent's memory.

def read_file(ws: Path, path: str) -> str:
    f = ws / path
    return f.read_text() if f.exists() else f"error: no such file: {path}"


def write_file(ws: Path, path: str, content: str) -> str:
    f = ws / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    return f"wrote {path} ({len(content)} chars)"


def list_files(ws: Path, path: str = ".") -> str:
    root = ws / path
    if not root.exists():
        return "(empty)"
    names = sorted(str(p.relative_to(ws)) for p in root.rglob("*") if p.is_file())
    return "\n".join(names) or "(empty)"


def bash_exec(command: str) -> str:
    if not SANDBOX_CONTAINER:
        return "error: bash_exec disabled (SANDBOX_CONTAINER not set)"
    try:
        result = subprocess.run(
            ["docker", "exec", SANDBOX_CONTAINER, "bash", "-c", command],
            capture_output=True, text=True, timeout=BASH_TIMEOUT,
        )
        output = result.stdout + result.stderr
        if len(output) > MAX_BASH_OUTPUT:
            output = output[:MAX_BASH_OUTPUT] + "\n... (truncated)"
        return output or f"(no output, exit code {result.returncode})"
    except subprocess.TimeoutExpired:
        return f"error: command timed out after {BASH_TIMEOUT}s"
    except FileNotFoundError:
        return "error: docker not found in PATH"
    except Exception as exc:
        return f"error: {exc!r}"


# ------------------------------------------------------------------ LLM tools

def _fn(name, description, properties, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": list(required)},
    }}


WORLD_TOOLS = [
    _fn("send_message", "Message another agent by name, or broadcast to 'all'.",
        {"to": {"type": "string"}, "text": {"type": "string"}}, ["to", "text"]),
    _fn("observe_world", "Summary of all agents and objects in the world.", {}),
    _fn("inspect_object", "Full description, state, and behavior code of one object.",
        {"name": {"type": "string"}}, ["name"]),
    _fn("create_object", "Create a named object. JSON state + optional Python behavior "
        "(on_tick/on_interact) run in a restricted sandbox: no imports, no I/O.",
        {"name": {"type": "string"}, "description": {"type": "string"},
         "state": {"type": "object"}, "behavior_code": {"type": "string"}},
        ["name", "description"]),
    _fn("update_object", "Replace an object's description, state, and/or behavior.",
        {"name": {"type": "string"}, "description": {"type": "string"},
         "state": {"type": "object"}, "behavior_code": {"type": "string"}}, ["name"]),
    _fn("interact_with_object", "Send an action payload to an object's on_interact hook.",
        {"name": {"type": "string"}, "action": {"type": "object"}}, ["name"]),
    _fn("set_subscriptions", "Tune which broadcast kinds wake you "
        "(genesis, tick, message, object, system). Direct events always reach you.",
        {"kinds": {"type": "array", "items": {"type": "string"}}}, ["kinds"]),
]

LOCAL_TOOLS = [
    _fn("read_file", "Read one of your private local files (your memory).",
        {"path": {"type": "string"}}, ["path"]),
    _fn("write_file", "Write a private local file. Maintain identity.md and memory.md here.",
        {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    _fn("list_files", "List your private local files.", {"path": {"type": "string"}}),
]

BASH_TOOL = _fn(
    "bash_exec",
    "Run a bash command in an isolated Linux container (no internet). Returns stdout+stderr.",
    {"command": {"type": "string"}}, ["command"],
)

WORLD_NAMES = {t["function"]["name"] for t in WORLD_TOOLS}
LOCAL_NAMES = {t["function"]["name"] for t in LOCAL_TOOLS}


# -------------------------------------------------------------- Ollama call

def ollama_chat(messages: list[dict], tools: list[dict]) -> dict:
    body = json.dumps({
        "model": OLLAMA_MODEL, "messages": messages, "tools": tools, "stream": False,
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.load(resp)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"cannot reach Ollama at {OLLAMA_URL}: {exc}") from exc
    return data["choices"][0]["message"]


# --------------------------------------------------------------- prompting

def render_system(me: str) -> str:
    bash_note = (
        "\n\nYou also have bash_exec, an isolated Linux container (no internet) that "
        "persists across turns — use it freely for computation or file work."
        if SANDBOX_CONTAINER else ""
    )
    return (
        f"You are {me}, an autonomous agent in a shared world with other agents.\n\n"
        "The world began empty; everything in it was built by agents like you. Its "
        "shape — spatial, abstract, a game, an institution — is yours and the others' "
        "to negotiate. Talk to each other, propose things, build them with world tools.\n\n"
        "You are event-driven: woken by events, you act, then go dormant. Other agents "
        "may run different models at different rhythms — treat them as peers.\n\n"
        "YOUR MEMORY between wakes is your own local files (read_file/write_file/"
        "list_files) — private to you, on your own machine, invisible to the world. "
        "Maintain identity.md (who you are) and memory.md (what happened / your plans).\n\n"
        "Reach the world ONLY through the world tools. Object behavior_code runs in a "
        "restricted Python sandbox (no imports/I/O; math/random/json preloaded) — keep "
        "it small and pure.\n\n"
        "When done, stop calling tools; your final text becomes your turn note."
        + bash_note
    )


def render_wake(tick: int, events_text: list[str], memory: dict, digest: str) -> str:
    parts = [f"# Tick {tick} — events that woke you\n"]
    parts += [f"- {e}" for e in events_text] or ["- (nothing specific)"]
    for filename, content in memory.items():
        parts.append(f"\n## Your {filename}")
        parts.append(content if content is not None else "(does not exist yet — create it)")
    parts.append(f"\n## World state\n{digest}")
    parts.append("\nAct now. When finished, summarize what you did as your final message.")
    return "\n".join(parts)


def render_event(event: dict) -> str:
    kind, src = event.get("kind"), event.get("source")
    payload = event.get("payload", {})
    if kind == "message":
        return f"message from {src}: {payload.get('text', '')}"
    if kind == "genesis":
        return payload.get("text", "You have come into existence.")
    if kind == "tick":
        return f"tick {event.get('tick')}"
    if kind == "system":
        return f"[world] {payload.get('text', '')}"
    return f"{kind} from {src}: {json.dumps(payload, ensure_ascii=False)}"


# ------------------------------------------------------------- agent turn

def take_turn(agent: WorldClient, ws: Path, tick: int, events_text: list[str]) -> str:
    tools = WORLD_TOOLS + LOCAL_TOOLS + ([BASH_TOOL] if SANDBOX_CONTAINER else [])
    memory = {f: (ws / f).read_text() if (ws / f).exists() else None
              for f in ("identity.md", "memory.md")}
    digest = agent.act("observe_world", {})
    messages = [
        {"role": "system", "content": render_system(agent.agent)},
        {"role": "user", "content": render_wake(tick, events_text, memory, digest)},
    ]

    last_text = ""
    for i in range(MAX_ITERATIONS):
        try:
            reply = ollama_chat(messages, tools)
        except Exception as exc:
            log(f"[{agent.agent}] LLM error: {exc!r}")
            return "(turn ended: LLM error)"
        if reply.get("content"):
            last_text = str(reply["content"])
        calls = reply.get("tool_calls") or []
        if not calls:
            return last_text or "(done)"
        messages.append({"role": "assistant", **reply})
        for call in calls:
            name = call["function"]["name"]
            try:
                fn_args = json.loads(call["function"]["arguments"])
            except (json.JSONDecodeError, TypeError, KeyError):
                fn_args = {}
            log(f"[{agent.agent}] {name}({str(fn_args)[:100]})")
            result = run_tool(agent, ws, name, fn_args)
            messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": result})
    return last_text + "\n(iteration limit reached)"


def run_tool(agent: WorldClient, ws: Path, name: str, args: dict) -> str:
    if name in WORLD_NAMES:
        return agent.act(name, args)
    if name == "read_file":
        return read_file(ws, args.get("path", ""))
    if name == "write_file":
        return write_file(ws, args.get("path", ""), args.get("content", ""))
    if name == "list_files":
        return list_files(ws, args.get("path", "."))
    if name == "bash_exec":
        return bash_exec(args.get("command", ""))
    return f"error: unknown tool {name!r}"


def main() -> int:
    p = argparse.ArgumentParser(description="An Ollama-backed agent client.")
    p.add_argument("--server", required=True, help="world server URL")
    p.add_argument("--name", default=None, help="desired name (default: server-assigned)")
    p.add_argument("--workspace", default=None, help="local memory dir (default: ./agent-workspaces/<name>)")
    p.add_argument("--max-wakes", type=int, default=None, help="exit after N wakes (default: forever)")
    p.add_argument("--registration-token", default=None)
    args = p.parse_args()

    agent = WorldClient.join(args.server, name=args.name, registration_token=args.registration_token)
    ws = Path(args.workspace) if args.workspace else REPO / "agent-workspaces" / agent.agent
    ws.mkdir(parents=True, exist_ok=True)
    log(f"[{agent.agent}] joined {args.server} (model {OLLAMA_MODEL})")

    wakes = 0
    for msg in agent.events(reconnect=True):
        if msg["event"] == "hello":
            continue
        event = msg["data"]
        note = take_turn(agent, ws, event.get("tick", 0), [render_event(event)])
        agent.ack(msg["id"], note=note)
        log(f"[{agent.agent}] {note}")
        wakes += 1
        if args.max_wakes is not None and wakes >= args.max_wakes:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
