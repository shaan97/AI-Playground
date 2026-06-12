"""Sandboxed execution of agent-written object behavior code.

Each hook call runs in a fresh, isolated Python subprocess:

- `python -I` (isolated mode: no site-packages, no env-var injection, no cwd
  on sys.path)
- whitelisted builtins only — no `open`, no `__import__`, no `eval`/`exec`,
  so behavior code cannot import modules or touch files/network through the
  normal paths; `math`, `random`, and `json` are pre-loaded as conveniences
- CPU-time and address-space rlimits, plus a wall-clock timeout enforced by
  the parent
- communication is JSON over stdin/stdout only

This contains accidents and casual misbehavior (infinite loops, memory bombs,
`import os`). It is NOT a formal security boundary — CPython sandboxing via
builtins filtering is known to be escapable by sufficiently adversarial code.
See SAFETY.md for the full threat model and the container recommendation.
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
    pass  # non-POSIX platform: wall-clock timeout still applies

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
    "__name__": "behavior",
    "math": math,
    "random": random,
    "json": json,
}

emitted = []

def _emit(p, to="all"):
    if not isinstance(p, dict):
        raise TypeError("emit payload must be a dict")
    emitted.append({"payload": p, "to": str(to)})

out = {
    "ok": True,
    "missing": False,
    "state": payload["state"],
    "emitted": [],
    "result": None,
    "error": None,
}
# Failures must be atomic: snapshot the input state so a hook that mutates
# and then raises reports the original, not a half-applied mutation.
_pristine_state = json.dumps(payload["state"])
try:
    exec(compile(payload["code"], "<behavior.py>", "exec"), _glb)
    hook = _glb.get(payload["hook"])
    if not callable(hook):
        out["missing"] = True
    else:
        state = payload["state"]
        if payload["hook"] == "on_tick":
            returned = hook(state, payload["world"], _emit)
            if isinstance(returned, dict):
                state = returned
        else:
            out["result"] = hook(state, payload["action"], payload["source"], _emit)
        out["state"] = state
        out["emitted"] = emitted
except BaseException as exc:
    out = {
        "ok": False,
        "missing": False,
        "state": json.loads(_pristine_state),
        "emitted": [],
        "result": None,
        "error": repr(exc),
    }

sys.stdout.write(json.dumps(out, default=str))
"""


@dataclass
class HookResult:
    ok: bool
    missing: bool = False
    state: dict = field(default_factory=dict)
    emitted: list[dict] = field(default_factory=list)  # [{"payload": ..., "to": ...}]
    result: object = None
    error: str | None = None


def run_hook(
    code: str,
    hook: str,
    state: dict,
    world: dict | None = None,
    action: dict | None = None,
    source: str | None = None,
    cpu_seconds: int = DEFAULT_CPU_SECONDS,
    memory_bytes: int = DEFAULT_MEMORY_BYTES,
    wall_timeout: float = DEFAULT_WALL_TIMEOUT,
) -> HookResult:
    payload = json.dumps(
        {
            "code": code,
            "hook": hook,
            "state": state,
            "world": world or {},
            "action": action or {},
            "source": source or "",
            "limits": {"cpu_seconds": cpu_seconds, "memory_bytes": memory_bytes},
        },
        default=str,
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _RUNNER],
            input=payload,
            capture_output=True,
            text=True,
            timeout=wall_timeout,
        )
    except subprocess.TimeoutExpired:
        return HookResult(ok=False, state=state, error=f"timed out after {wall_timeout}s")
    try:
        out = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        detail = (proc.stderr or proc.stdout or "no output").strip()[-500:]
        return HookResult(ok=False, state=state, error=f"sandbox crashed: {detail}")
    return HookResult(
        ok=bool(out.get("ok")),
        missing=bool(out.get("missing")),
        state=out.get("state") if isinstance(out.get("state"), dict) else state,
        emitted=[e for e in out.get("emitted", []) if isinstance(e, dict)],
        result=out.get("result"),
        error=str(out["error"]) if out.get("error") else None,
    )
