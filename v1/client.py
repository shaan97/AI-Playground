"""A thin, opaque-by-design client for a world server.

This is pure transport: register an identity, consume the event stream, invoke
world operations, acknowledge what you consumed. It knows nothing about models,
prompts, or memory — those belong to *your* harness, on *your* machine. Build
an agent by wrapping this in whatever decision loop you like (see examples/).

The world is just an HTTP+JSON API, so you don't need this module at all: any
language can speak the endpoints in PROTOCOL.md directly. It exists only as a
convenient reference for Python harnesses.

Stdlib-only (urllib).

    from client import WorldClient

    agent = WorldClient.join("http://127.0.0.1:8470", name="aria")
    for msg in agent.events():
        if msg["event"] == "hello":
            continue
        event = msg["data"]            # a world event dict
        # ... decide what to do (call your model here) ...
        agent.act("send_message", {"to": "all", "text": "hello"})
        agent.ack(msg["id"], note="said hi")
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


def register(
    server_url: str,
    name: str | None = None,
    registration_token: str | None = None,
    timeout: float = 30.0,
) -> tuple[str, str]:
    """Claim an identity in the world. Returns (name, token). The name may
    differ from the one requested only if you omit it (the server assigns one);
    a requested name is taken verbatim or the call fails."""
    server_url = server_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if registration_token:
        headers["X-Registration-Token"] = registration_token
    body = json.dumps({"name": name} if name else {}).encode()
    req = urllib.request.Request(
        server_url + "/register", data=body, method="POST", headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"registration failed ({exc.code}): {detail}") from None
    return payload["name"], payload["token"]


def fetch_spec(server_url: str, timeout: float = 30.0) -> list[dict]:
    """The world's action catalog (no auth needed) — feed it to your model as
    tool definitions, or ignore it and call actions by name."""
    with urllib.request.urlopen(server_url.rstrip("/") + "/spec", timeout=timeout) as resp:
        return json.loads(resp.read()).get("actions", [])


class WorldClient:
    def __init__(self, server_url: str, agent: str, token: str, wait: float = 5.0):
        self.server_url = server_url.rstrip("/")
        self.agent = agent
        self.token = token
        self.wait = wait  # reconnect backoff, seconds
        self.cursor = 0   # seq of the last event received

    @classmethod
    def join(
        cls,
        server_url: str,
        name: str | None = None,
        registration_token: str | None = None,
        wait: float = 5.0,
    ) -> "WorldClient":
        """Register and return a ready client."""
        name, token = register(server_url, name, registration_token)
        return cls(server_url, name, token, wait=wait)

    # ------------------------------------------------------------------ http

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            self.server_url + path,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return exc.code, {"error": raw.decode(errors="replace")}

    # ---------------------------------------------------------------- actions

    def act(self, action_name: str, action_input: dict) -> str:
        """Invoke one world operation; returns the result string (which may be
        an `error:`-prefixed message — action failures are not transport errors)."""
        status, body = self._post(
            f"/agents/{self.agent}/actions",
            {"name": action_name, "input": action_input},
        )
        if status != 200:
            return f"error: server returned {status}: {body.get('error', body)}"
        return str(body.get("content", ""))

    def ack(self, cursor: int, note: str = "") -> None:
        """Acknowledge consumption up to `cursor` (events with seq <= cursor are
        dropped from your inbox) and optionally log an observer-facing note."""
        self._post(f"/agents/{self.agent}/turns", {"note": note, "cursor": int(cursor)})

    # ----------------------------------------------------------------- events

    def events(self, timeout: float | None = None, reconnect: bool = False):
        """Yield messages from the SSE stream as dicts:
        `{"event": str|None, "id": int|None, "data": dict}`. The first message
        is `{"event": "hello", ...}` with a world snapshot; the rest are world
        events (`event` is None, `id` is the global seq, `data` is the event).

        With `timeout`, the generator ends if no data arrives for that many
        seconds (useful for tests). With `reconnect`, it transparently
        re-opens the stream (resuming from the last seq) instead of ending."""
        while True:
            try:
                yield from self._stream_once(timeout)
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                if not reconnect:
                    return
                time.sleep(min(self.wait, 5.0))
                continue
            if not reconnect:
                return
            time.sleep(min(self.wait, 5.0))

    def _stream_once(self, timeout: float | None):
        req = urllib.request.Request(
            f"{self.server_url}/agents/{self.agent}/events?cursor={self.cursor}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "text/event-stream",
            },
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        event_name: str | None = None
        event_id: int | None = None
        data_lines: list[str] = []
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line == "":  # blank line terminates one SSE frame
                if data_lines:
                    try:
                        data = json.loads("\n".join(data_lines))
                    except json.JSONDecodeError:
                        data = None
                    if data is not None:
                        yield {"event": event_name, "id": event_id, "data": data}
                event_name, event_id, data_lines = None, None, []
                continue
            if line.startswith(":"):  # comment / keepalive
                continue
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "event":
                event_name = value
            elif field == "data":
                data_lines.append(value)
            elif field == "id" and value.isdigit():
                event_id = int(value)
                self.cursor = event_id
