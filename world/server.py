"""The world as a server; agents live elsewhere, as clients.

Stdlib-only HTTP server over the same kernel as lockstep mode. Time is the
world's own: a wall-clock ticker drives `advance_tick()` (objects + tick
broadcast, default every 10 minutes), while agents connect whenever they
like, long-poll their inbox, act, and acknowledge what they consumed.

Concurrency model: a single world lock serializes every mutation, so the
append-only event log remains a total order — "two agents acted at once"
just means adjacent sequence numbers.

Endpoints (one JSON object in, one out; `Authorization: Bearer <token>`):

    GET  /world                          world digest             (any token)
    GET  /agents/<name>/wake?wait=30     long-poll a wake payload (agent token)
    POST /agents/<name>/actions          {"name", "input"}        (agent token)
    POST /agents/<name>/turns            {"note", "cursor"}       (agent token)
    POST /admin/inject                   {"text", "to"?}          (admin token)
    POST /admin/step                     advance one tick now     (admin token)

The wake payload is exactly the one in PROTOCOL.md plus a `cursor` field;
delivery is at-least-once: events stay queued until the client acknowledges
the cursor via POST /turns, so a crashed client sees them again on its next
wake.

Per-agent bearer tokens live in <data-dir>/tokens.json (auto-generated).
Binds to 127.0.0.1 by default — see SAFETY.md before exposing it wider.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .kernel import World
from .protocol import build_wake

DEFAULT_TICK_INTERVAL = 600.0  # 10 minutes
DEFAULT_RATE_LIMIT = 120  # actions per agent per minute
MAX_WAIT = 120.0
MAX_BODY = 2_000_000

_AGENT_PATH = re.compile(r"^/agents/([a-z0-9][a-z0-9_-]*)/(wake|actions|turns)$")


def load_or_create_tokens(root: Path, agent_names: list[str]) -> dict:
    """tokens.json: {"admin": <token>, "agents": {<name>: <token>}}."""
    path = root / "tokens.json"
    tokens = json.loads(path.read_text()) if path.exists() else {"admin": None, "agents": {}}
    tokens["admin"] = tokens.get("admin") or secrets.token_hex(16)
    agents = tokens.setdefault("agents", {})
    for name in agent_names:
        agents.setdefault(name, secrets.token_hex(16))
    path.write_text(json.dumps(tokens, indent=2))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return tokens


class WorldServer:
    def __init__(
        self,
        world: World,
        tokens: dict,
        host: str = "127.0.0.1",
        port: int = 8470,
        tick_interval: float = DEFAULT_TICK_INTERVAL,
        rate_limit: int = DEFAULT_RATE_LIMIT,
    ):
        self.world = world
        self.tokens = tokens
        self.tick_interval = tick_interval
        self.rate_limit = rate_limit
        self.lock = threading.RLock()
        self._action_times: dict[str, deque] = {name: deque() for name in world.agents}
        self._stop = threading.Event()

        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet; the world prints its own narration
                pass

            # ---------------------------------------------------- plumbing

            def _token(self) -> str:
                auth = self.headers.get("Authorization", "")
                return auth.removeprefix("Bearer ").strip()

            def _reply(self, code: int, obj: dict | None = None) -> None:
                body = json.dumps(obj).encode() if obj is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    raise ValueError("request body too large")
                raw = self.rfile.read(length) if length else b"{}"
                parsed = json.loads(raw or b"{}")
                if not isinstance(parsed, dict):
                    raise ValueError("request body must be a JSON object")
                return parsed

            def _authed_agent(self, name: str) -> bool:
                expected = server.tokens["agents"].get(name)
                return bool(expected) and secrets.compare_digest(self._token(), expected)

            def _authed_admin(self) -> bool:
                return secrets.compare_digest(self._token(), server.tokens["admin"])

            def _authed_any(self) -> bool:
                known = [server.tokens["admin"], *server.tokens["agents"].values()]
                return any(secrets.compare_digest(self._token(), t) for t in known)

            # ------------------------------------------------------ routes

            def do_GET(self):
                url = urlparse(self.path)
                if url.path == "/world":
                    if not self._authed_any():
                        return self._reply(403, {"error": "bad token"})
                    with server.lock:
                        return self._reply(200, {
                            "tick": server.world.tick,
                            "agents": list(server.world.agents),
                            "digest": server.world.digest(),
                        })
                m = _AGENT_PATH.match(url.path)
                if m and m.group(2) == "wake":
                    name = m.group(1)
                    if name not in server.world.agents:
                        return self._reply(404, {"error": f"no such agent {name!r}"})
                    if not self._authed_agent(name):
                        return self._reply(403, {"error": "bad token"})
                    wait = min(float(parse_qs(url.query).get("wait", ["30"])[0]), MAX_WAIT)
                    wake = server.await_wake(name, wait)
                    if wake is None:
                        return self._reply(204)
                    return self._reply(200, wake)
                return self._reply(404, {"error": "not found"})

            def do_POST(self):
                url = urlparse(self.path)
                try:
                    body = self._body()
                except (ValueError, json.JSONDecodeError) as exc:
                    return self._reply(400, {"error": str(exc)})

                if url.path == "/admin/inject":
                    if not self._authed_admin():
                        return self._reply(403, {"error": "bad token"})
                    with server.lock:
                        server.world.inject(str(body.get("text", "")), to=str(body.get("to", "all")))
                    return self._reply(200, {"ok": True})

                if url.path == "/admin/step":
                    if not self._authed_admin():
                        return self._reply(403, {"error": "bad token"})
                    with server.lock:
                        server.world.advance_tick()
                        return self._reply(200, {"tick": server.world.tick})

                m = _AGENT_PATH.match(url.path)
                if not m:
                    return self._reply(404, {"error": "not found"})
                name, endpoint = m.group(1), m.group(2)
                if name not in server.world.agents:
                    return self._reply(404, {"error": f"no such agent {name!r}"})
                if not self._authed_agent(name):
                    return self._reply(403, {"error": "bad token"})

                if endpoint == "actions":
                    if not server.allow_action(name):
                        return self._reply(429, {
                            "error": f"rate limit: max {server.rate_limit} actions/minute"
                        })
                    with server.lock:
                        content = server.world.agents[name].dispatch(
                            str(body.get("name", "")), dict(body.get("input") or {})
                        )
                        server.world._save_meta()
                    return self._reply(200, {"content": content})

                if endpoint == "turns":
                    with server.lock:
                        server.world.record_turn(name, str(body.get("note", "")))
                        server.world.ack(name, int(body.get("cursor", 0)))
                    return self._reply(200, {"ok": True})

                return self._reply(404, {"error": "not found"})

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.host, self.port = self.httpd.server_address[:2]

    # ------------------------------------------------------------------ core

    def await_wake(self, name: str, wait: float) -> dict | None:
        """Long-poll: return a wake payload as soon as the agent has pending
        events, or None after `wait` seconds."""
        deadline = time.monotonic() + wait
        while not self._stop.is_set():
            with self.lock:
                pending = list(self.world.inboxes[name])
                if pending:
                    wake = build_wake(self.world.agents[name], pending, self.world)
                    wake["cursor"] = max(e.seq for e in pending)
                    return wake
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.2)
        return None

    def allow_action(self, name: str) -> bool:
        now = time.monotonic()
        times = self._action_times[name]
        while times and now - times[0] > 60.0:
            times.popleft()
        if len(times) >= self.rate_limit:
            return False
        times.append(now)
        return True

    # --------------------------------------------------------------- running

    def _ticker(self) -> None:
        while not self._stop.wait(self.tick_interval):
            with self.lock:
                self.world.advance_tick()

    def start(self) -> None:
        """Start serving in background threads (genesis included)."""
        with self.lock:
            self.world.ensure_genesis()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        if self.tick_interval > 0:
            threading.Thread(target=self._ticker, daemon=True).start()

    def serve_forever(self) -> None:
        self.start()
        try:
            while not self._stop.wait(1.0):
                pass
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._stop.set()
        self.httpd.shutdown()
        with self.lock:
            self.world._save_meta()
