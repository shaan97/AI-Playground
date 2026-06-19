"""The world as an HTTP server; agents live elsewhere, as opaque clients.

Stdlib-only HTTP server over the kernel. Time is the world's own: a wall-clock
ticker drives `advance_tick()` (objects + tick broadcast, default every 10
minutes), while agents register, open an event stream, act, and acknowledge
what they consumed — each on its own cadence.

Server -> client delivery is **Server-Sent Events**. A client opens one
long-lived `GET /agents/<name>/events`; the server replays everything past the
client's cursor, then streams new events live as `id: <seq>` / `data: <json>`
frames. The durable inbox + global `seq` + cursor-ack contract sits underneath
and is transport-agnostic: events stay queued until acked via `POST .../turns`,
so a crashed client sees them again when it reconnects (at-least-once).

Concurrency model: a single world lock serializes every mutation, so the
append-only event log remains a total order — "two agents acted at once" just
means adjacent sequence numbers.

Endpoints (`Authorization: Bearer <token>` unless noted):

    POST /register                       {name?}  -> {name, token}   (open*)
    GET  /spec                           the action catalog          (open)
    GET  /world                          world digest                (any token)
    GET  /agents/<name>/events           SSE stream                  (agent token)
    POST /agents/<name>/actions          {name, input}               (agent token)
    POST /agents/<name>/turns            {note, cursor}              (agent token)
    POST /admin/inject                   {text, to?}                 (admin token)
    POST /admin/step                     advance one tick now        (admin token)

*Registration is open by default; pass a `registration_token` to gate it behind
an `X-Registration-Token` header. Per-agent bearer tokens are minted on
registration and stored in <data-dir>/tokens.json. Binds to 127.0.0.1 by
default — see SAFETY.md before exposing it wider.
"""

from __future__ import annotations

import json
import re
import secrets
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .kernel import InvalidName, NameTaken, World
from .protocol import ACTIONS

DEFAULT_TICK_INTERVAL = 600.0  # 10 minutes
DEFAULT_RATE_LIMIT = 120  # actions per agent per minute
MAX_BODY = 2_000_000
SSE_POLL = 0.25  # seconds between inbox polls on a live stream
SSE_KEEPALIVE = 15.0  # seconds of idleness before a keepalive comment

_AGENT_PATH = re.compile(r"^/agents/([a-z0-9][a-z0-9_-]*)/(events|actions|turns)$")


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True  # held SSE connections never block process exit

    def handle_error(self, request, client_address):
        # SSE clients disconnect routinely; a reset/abort/broken pipe is normal,
        # not a server error worth a traceback.
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def load_or_create_tokens(root: Path, agent_names: list[str] | None = None) -> dict:
    """tokens.json: {"admin": <token>, "agents": {<name>: <token>}}.

    Ensures an admin token and a token for each pre-seeded name; agents that
    register later get their tokens minted on the fly.
    """
    path = root / "tokens.json"
    tokens = json.loads(path.read_text()) if path.exists() else {"admin": None, "agents": {}}
    tokens["admin"] = tokens.get("admin") or secrets.token_hex(16)
    agents = tokens.setdefault("agents", {})
    for name in agent_names or []:
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
        registration_token: str | None = None,
    ):
        self.world = world
        self.tokens = tokens
        self.tokens_path = world.root / "tokens.json"
        self.tick_interval = tick_interval
        self.rate_limit = rate_limit
        self.registration_token = registration_token
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
                if url.path == "/spec":
                    return self._reply(200, {"actions": [a.to_dict() for a in ACTIONS]})
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
                if m and m.group(2) == "events":
                    name = m.group(1)
                    if name not in server.world.agents:
                        return self._reply(404, {"error": f"no such agent {name!r}"})
                    if not self._authed_agent(name):
                        return self._reply(403, {"error": "bad token"})
                    return self._stream(name, url)
                return self._reply(404, {"error": "not found"})

            def do_POST(self):
                url = urlparse(self.path)
                try:
                    body = self._body()
                except (ValueError, json.JSONDecodeError) as exc:
                    return self._reply(400, {"error": str(exc)})

                if url.path == "/register":
                    if server.registration_token is not None:
                        provided = self.headers.get("X-Registration-Token", "")
                        if not secrets.compare_digest(provided, server.registration_token):
                            return self._reply(403, {"error": "registration requires a valid X-Registration-Token"})
                    try:
                        name, token = server.register_agent(str(body.get("name", "")) or None)
                    except InvalidName as exc:
                        return self._reply(400, {"error": str(exc)})
                    except NameTaken as exc:
                        return self._reply(409, {"error": str(exc)})
                    return self._reply(200, {"name": name, "token": token})

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
                        content = server.world.apply_action(
                            name, str(body.get("name", "")), dict(body.get("input") or {})
                        )
                        server.world._save_meta()
                    return self._reply(200, {"content": content})

                if endpoint == "turns":
                    with server.lock:
                        server.world.record_turn(name, str(body.get("note", "")))
                        server.world.ack(name, int(body.get("cursor", 0)))
                    return self._reply(200, {"ok": True})

                return self._reply(404, {"error": "not found"})

            # -------------------------------------------------------- SSE

            def _stream(self, name: str, url) -> None:
                # Resume point: SSE Last-Event-ID header (set automatically by
                # the browser/EventSource on reconnect) or an explicit ?cursor=.
                cursor = self.headers.get("Last-Event-ID")
                if cursor is None:
                    cursor = parse_qs(url.query).get("cursor", ["0"])[0]
                try:
                    last_sent = int(cursor)
                except (TypeError, ValueError):
                    last_sent = 0

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")  # disable proxy buffering
                self.end_headers()

                with server.lock:
                    hello = {
                        "tick": server.world.tick,
                        "agents": list(server.world.agents),
                        "digest": server.world.digest(),
                        "subscriptions": list(server.world.subscriptions.get(name, [])),
                    }
                if not self._send(event="hello", data=hello):
                    return

                last_activity = time.monotonic()
                while not server._stop.is_set():
                    with server.lock:
                        pending = [e for e in server.world.inboxes.get(name, []) if e.seq > last_sent]
                    for event in pending:
                        if not self._send(data=event.to_dict(), event_id=event.seq):
                            return
                        last_sent = event.seq
                        last_activity = time.monotonic()
                    if not pending and time.monotonic() - last_activity > SSE_KEEPALIVE:
                        if not self._send_raw(": keepalive\n\n"):
                            return
                        last_activity = time.monotonic()
                    time.sleep(SSE_POLL)

            def _send(self, data: dict, event: str | None = None, event_id=None) -> bool:
                buf = ""
                if event is not None:
                    buf += f"event: {event}\n"
                if event_id is not None:
                    buf += f"id: {event_id}\n"
                buf += f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                return self._send_raw(buf)

            def _send_raw(self, text: str) -> bool:
                try:
                    self.wfile.write(text.encode())
                    self.wfile.flush()
                    return True
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return False  # client went away; end the stream

        self.httpd = _QuietThreadingHTTPServer((host, port), Handler)
        self.host, self.port = self.httpd.server_address[:2]

    # ------------------------------------------------------------------ core

    def register_agent(self, name: str | None = None) -> tuple[str, str]:
        """Admit an agent and mint+persist its bearer token. Propagates
        InvalidName / NameTaken from the kernel."""
        with self.lock:
            actual = self.world.register(name)
            token = secrets.token_hex(16)
            self.tokens["agents"][actual] = token
            self._action_times.setdefault(actual, deque())
            self._save_tokens()
        return actual, token

    def _save_tokens(self) -> None:
        self.tokens_path.write_text(json.dumps(self.tokens, indent=2))
        try:
            self.tokens_path.chmod(0o600)
        except OSError:
            pass

    def allow_action(self, name: str) -> bool:
        now = time.monotonic()
        times = self._action_times.setdefault(name, deque())
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
        """Start serving in background threads."""
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
