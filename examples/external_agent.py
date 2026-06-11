#!/usr/bin/env python3
"""A complete external agent harness speaking the world wire protocol.

Stdlib-only and model-free, so it doubles as a template: everything below
`--- decision logic ---` is the part you'd replace with calls to your own
model or agent framework (any vendor, any language — see PROTOCOL.md).

Run a world where every agent is this harness:

    python run_world.py --agent-cmd "python examples/external_agent.py" --ticks 3
"""

from __future__ import annotations

import json
import os
import sys


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


def log(text: str) -> None:
    print(text, file=sys.stderr, flush=True)  # stderr = harness debug channel


# --- decision logic (replace this with your model) ---------------------------

GUESTBOOK_BEHAVIOR = """\
def on_interact(state, action, source, emit):
    entry = {"by": source, "text": str(action.get("text", ""))}
    state["entries"].append(entry)
    emit({"guestbook_signed": entry})
    return {"entries_total": len(state["entries"])}
"""


def main() -> None:
    wake = recv()
    if not wake or wake.get("type") != "wake":
        return
    me = wake["agent"]
    tick = wake["tick"]
    events = wake["events"]

    # The workspace is a plain directory we own — direct file access is as
    # valid as the read_file/write_file actions.
    workspace = wake["workspace"] or os.environ.get("WORLD_WORKSPACE", ".")
    with open(os.path.join(workspace, "memory.md"), "a") as f:
        f.write(f"tick {tick}: woke with {len(events)} event(s)\n")

    if any(e["kind"] == "genesis" for e in events):
        act("write_file", {
            "path": "identity.md",
            "content": f"I am {me}, an agent driven by an external harness over the wire protocol.\n",
        })
        act("send_message", {
            "to": "all",
            "text": f"Hello — {me} here, speaking from outside via the wire protocol. "
                    "I've left a guestbook; interact with it to sign.",
        })
        result = act("create_object", {
            "name": "guestbook",
            "description": "A guestbook anyone can sign by interacting with {\"text\": ...}.",
            "state": {"entries": []},
            "behavior_code": GUESTBOOK_BEHAVIOR,
        })
        log(f"{me}: guestbook -> {result}")
        send({"type": "end_turn", "note": "Introduced myself and opened a guestbook."})
        return

    messages = [e for e in events if e["kind"] == "message"]
    if messages:
        result = act("interact_with_object", {
            "name": "guestbook",
            "action": {"text": f"{me} heard {len(messages)} message(s) on tick {tick}"},
        })
        log(f"{me}: signed guestbook -> {result}")
        send({"type": "end_turn", "note": f"Heard {len(messages)} message(s); signed the guestbook."})
        return

    send({"type": "end_turn", "note": "Quiet tick; updated my memory."})


if __name__ == "__main__":
    main()
