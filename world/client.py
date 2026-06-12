"""An agent client: lives outside the world, connects over HTTP.

The client owns the agent's cadence — it long-polls the server for a wake
payload, drives a local connector (Claude, an external harness process, a
mock, ...) through the turn, proxying every action to the server, then
acknowledges the consumed events. The same connectors used in lockstep mode
work here unchanged.

Stdlib-only (urllib).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class WorldClient:
    def __init__(
        self,
        server_url: str,
        agent: str,
        token: str,
        connector,
        wait: float = 60.0,
        quiet: bool = False,
    ):
        self.server_url = server_url.rstrip("/")
        self.agent = agent
        self.token = token
        self.connector = connector
        self.wait = wait
        self.quiet = quiet

    # ------------------------------------------------------------------ http

    def _request(self, method: str, path: str, body: dict | None = None,
                 timeout: float | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.server_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or 30.0) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return exc.code, {"error": raw.decode(errors="replace")}

    # ----------------------------------------------------------------- agent

    def dispatch(self, action_name: str, action_input: dict) -> str:
        status, body = self._request(
            "POST",
            f"/agents/{self.agent}/actions",
            {"name": action_name, "input": action_input},
        )
        if status != 200:
            return f"error: server returned {status}: {body.get('error', body)}"
        return str(body.get("content", ""))

    def _await_wake(self) -> dict | None:
        status, body = self._request(
            "GET",
            f"/agents/{self.agent}/wake?wait={self.wait:g}",
            timeout=self.wait + 30.0,
        )
        if status == 200 and body.get("type") == "wake":
            return body
        return None  # 204: nothing yet — poll again

    def _say(self, text: str) -> None:
        if not self.quiet:
            print(text, flush=True)

    def run(self, max_wakes: int | None = None) -> int:
        """Live: wake on events, act, acknowledge, repeat. Returns the number
        of wakes taken (useful with max_wakes; otherwise runs until killed)."""
        wakes = 0
        while max_wakes is None or wakes < max_wakes:
            try:
                wake = self._await_wake()
            except urllib.error.URLError as exc:
                self._say(f"[{self.agent}] server unreachable ({exc.reason}); retrying...")
                time.sleep(min(self.wait, 10.0))
                continue
            if wake is None:
                continue
            self._say(
                f"[{self.agent}] woke at tick {wake['tick']} "
                f"with {len(wake['events'])} event(s)"
            )
            note = self.connector.take_turn(wake, self.dispatch)
            self._request(
                "POST",
                f"/agents/{self.agent}/turns",
                {"note": note, "cursor": wake["cursor"]},
            )
            self._say(f"[{self.agent}] {note}")
            wakes += 1
        return wakes
