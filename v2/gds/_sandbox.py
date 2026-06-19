"""Isolated execution of author-written transition code (ported from v1).

Each `LocalKernel.evaluate` runs the author's `transition` in a fresh, isolated
subprocess:

* ``python -I`` (no site-packages, no env injection, no cwd on ``sys.path``);
* whitelisted builtins — no ``open``/``__import__``/``eval``/``exec``; ``math``,
  ``random`` and ``json`` are pre-loaded (an author may use randomness or not,
  seed it or not — the substrate has no opinion);
* CPU-time and address-space rlimits plus a parent wall-clock timeout;
* JSON-only communication.

The author contract::

    def transition(state, inputs, emit):
        # state  : this vertex's current state
        # inputs : {observed_vertex: its_state} for v in N⁺(self)
        # emit(effect_dict): queue a topology update, one of
        #     {"op": "add_arc",    "target": <vertex>}
        #     {"op": "remove_arc", "target": <vertex>}
        #     {"op": "add_vertex", "state": <json>, "code": <str>,
        #      "observes": [<vertex>, ...]}
        # return the next state (or None to keep the current state)

This contains accidents and casual misbehaviour, not a determined adversary; see
``docs/UNIVERSE.md`` / the v2 safety notes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field

DEFAULT_CPU_SECONDS = 5
DEFAULT_MEMORY_BYTES = 512 * 1024 * 1024
DEFAULT_WALL_TIMEOUT = 10.0

_RUNNER = r"""
import json, sys

payload = json.loads(sys.stdin.read())

try:
    import resource
    cpu = payload["limits"]["cpu_seconds"]
    mem = payload["limits"]["memory_bytes"]
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
except Exception:
    pass  # non-POSIX (e.g. Windows): the parent wall-clock timeout still applies

import builtins as _b

_ALLOWED = [
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
    "callable", "chr", "complex", "dict", "divmod", "enumerate", "filter",
    "float", "format", "frozenset", "hasattr", "hash", "hex", "int",
    "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min",
    "next", "object", "oct", "ord", "pow", "range", "repr", "reversed",
    "round", "set", "slice", "sorted", "str", "sum", "tuple", "type", "zip",
    "__build_class__",
    "ArithmeticError", "AssertionError", "AttributeError", "BaseException",
    "Exception", "IndexError", "KeyError", "LookupError", "NameError",
    "NotImplementedError", "OverflowError", "RuntimeError", "StopIteration",
    "TypeError", "ValueError", "ZeroDivisionError",
]
_safe = {name: getattr(_b, name) for name in _ALLOWED if hasattr(_b, name)}

import math, random
_glb = {
    "__builtins__": _safe,
    "__name__": "transition_module",
    "math": math,
    "random": random,
    "json": json,
}

emitted = []

_ALLOWED_OPS = {"add_arc", "remove_arc", "add_vertex"}

def _emit(effect):
    if not isinstance(effect, dict) or effect.get("op") not in _ALLOWED_OPS:
        raise ValueError("emit expects {'op': 'add_arc'|'remove_arc'|'add_vertex', ...}")
    emitted.append(effect)

out = {"ok": True, "next_state": payload["state"], "effects": [], "error": None}
# Atomic failure: snapshot the input so a transition that mutates then raises
# reports the original state, not a half-applied mutation.
_pristine = json.dumps(payload["state"])
try:
    exec(compile(payload["code"], "<transition.py>", "exec"), _glb)
    fn = _glb.get("transition")
    if not callable(fn):
        out = {"ok": False, "next_state": json.loads(_pristine), "effects": [],
               "error": "no callable 'transition(state, inputs, emit)' defined"}
    else:
        returned = fn(payload["state"], payload["inputs"], _emit)
        out["next_state"] = payload["state"] if returned is None else returned
        out["effects"] = emitted
except BaseException as exc:
    out = {"ok": False, "next_state": json.loads(_pristine), "effects": [],
           "error": repr(exc)}

sys.stdout.write(json.dumps(out, default=str))
"""


@dataclass
class SandboxResult:
    ok: bool
    next_state: object = None
    effects: list = field(default_factory=list)
    error: str | None = None


def run_transition(
    code: str,
    state: object,
    inputs: dict,
    cpu_seconds: int = DEFAULT_CPU_SECONDS,
    memory_bytes: int = DEFAULT_MEMORY_BYTES,
    wall_timeout: float = DEFAULT_WALL_TIMEOUT,
) -> SandboxResult:
    payload = json.dumps(
        {
            "code": code,
            "state": state,
            "inputs": inputs,
            "limits": {"cpu_seconds": cpu_seconds, "memory_bytes": memory_bytes},
        },
        default=str,
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _RUNNER],
            input=payload, capture_output=True, text=True, timeout=wall_timeout,
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(ok=False, next_state=state, error=f"timed out after {wall_timeout}s")
    try:
        out = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        detail = (proc.stderr or proc.stdout or "no output").strip()[-500:]
        return SandboxResult(ok=False, next_state=state, error=f"sandbox crashed: {detail}")
    return SandboxResult(
        ok=bool(out.get("ok")),
        next_state=out.get("next_state", state),
        effects=[e for e in out.get("effects", []) if isinstance(e, dict)],
        error=str(out["error"]) if out.get("error") else None,
    )
