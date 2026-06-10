"""Events are the only thing agents perceive.

Every event has a kind, the tick it occurred on, a source (the world, an
agent, or an object), a recipient ("all" or an agent name), and a free-form
JSON payload.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

GENESIS = "genesis"
TICK = "tick"
MESSAGE = "message"
OBJECT = "object"
SYSTEM = "system"


@dataclass
class Event:
    kind: str
    tick: int
    source: str
    to: str = "all"
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        """Compact one-event text shown to an agent in its turn prompt."""
        if self.kind == GENESIS:
            return f"[genesis] {self.payload.get('text', 'You have come into existence.')}"
        if self.kind == TICK:
            return f"[tick {self.tick}] The clock advances."
        if self.kind == MESSAGE:
            scope = "to you" if self.to != "all" else "to everyone"
            return f"[message {scope}] {self.source} says: {self.payload.get('text', '')}"
        if self.kind == OBJECT:
            if "error" in self.payload:
                return (
                    f"[object error] '{self.source}' raised an error while running: "
                    f"{self.payload['error']}"
                )
            return f"[object '{self.source}'] {json.dumps(self.payload, ensure_ascii=False)}"
        if self.kind == SYSTEM:
            return f"[world] {self.payload.get('text', '')}"
        return f"[{self.kind}] {json.dumps(self.payload, ensure_ascii=False)}"
