"""The Universe control plane — a long-lived, stdlib-only web app.

Unlike ``serve_gds`` (which bolts a viewer onto a *single* in-process run), this
server outlives any individual run. It is the website you open to:

- **browse every run** (live or archived) — the filesystem ``runs/`` directory is
  the source of truth, read through :class:`viewer.runs.RunStore`;
- **watch one run** evolve (graph + per-step trace) and **read its whole
  trajectory** as one scrollable transcript (the Antigravity-style view);
- **launch new experiments** and **pause/stop** them — when a :class:`JobManager`
  is wired in (``jobs`` argument); with ``jobs=None`` the launcher is disabled
  and the server is a pure read surface.

A live run is just a run directory whose files are still being appended to, so
history and live-tailing share one code path: the SSE stream polls the run's
``trajectory.jsonl`` and emits a ``step`` event per newly appended configuration.

Zero dependencies (``http.server`` + a single static HTML page). Intended for a
single operator on a private tailnet; it exposes no auth (see README/SAFETY).
"""

from __future__ import annotations

import json
import queue
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

from .runs import LIVE_STATES, RunStore
from .server import _QuietThreadingHTTPServer, _lan_ip  # reuse transport helpers

STATIC_DIR = Path(__file__).resolve().parent / "static"
POLL_SECONDS = 0.3      # how often the SSE tailer checks a live run for new steps
HEARTBEAT_SECONDS = 15  # SSE comment ping so proxies/phones keep the stream open


def _control_of(state: str) -> str:
    """Map a run-state to the operator pill's running/paused/stopped vocabulary."""
    return {"running": "running", "paused": "paused"}.get(state, "stopped")


def _make_handler(store: RunStore, jobs):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        # ---------------------------------------------------------- helpers
        def _json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path, content_type: str):
            try:
                body = path.read_bytes()
            except OSError:
                self._json({"error": "not found"}, status=404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except ValueError:
                return {}

        _CONTENT_TYPES = {".js": "application/javascript; charset=utf-8",
                          ".css": "text/css; charset=utf-8",
                          ".html": "text/html; charset=utf-8",
                          ".svg": "image/svg+xml", ".json": "application/json"}

        def _static(self, name: str):
            # Serve only files directly under static/ — no path traversal.
            safe = Path(name).name
            path = STATIC_DIR / safe
            if not safe or not path.is_file():
                self._json({"error": "not found"}, status=404)
                return
            self._file(path, self._CONTENT_TYPES.get(path.suffix, "application/octet-stream"))

        def log_message(self, *args):  # quiet by default
            pass

        # ---------------------------------------------------------- routing
        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path == "/":
                self._file(STATIC_DIR / "app.html", "text/html; charset=utf-8")
                return
            if path.startswith("/static/"):
                self._static(path[len("/static/"):])
                return
            if path == "/api/runs":
                self._json(store.list_runs())
                return
            if path.startswith("/api/runs/"):
                self._run_route(path[len("/api/runs/"):], parsed, method="GET")
                return
            self._json({"error": "not found"}, status=404)

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path == "/api/runs":
                self._launch()
                return
            if path.startswith("/api/runs/"):
                self._run_route(path[len("/api/runs/"):], parsed, method="POST")
                return
            self._json({"error": "not found"}, status=404)

        # ------------------------------------------------- per-run dispatch
        def _run_route(self, rest: str, parsed, method: str):
            parts = rest.split("/")
            run_id = unquote(parts[0])
            tail = parts[1:]

            if method == "GET" and tail and tail[0] == "stream":
                self._stream(run_id, parsed)
                return

            if method == "POST" and tail and tail[0] == "control":
                self._control(run_id, tail[1] if len(tail) > 1 else "")
                return

            # All remaining routes are reads that require the run to exist.
            if not store.exists(run_id):
                self._json({"error": "unknown run"}, status=404)
                return

            if not tail or tail == [""]:
                self._json(store.summary(run_id))
            elif tail[0] == "meta":
                self._json(store.meta(run_id))
            elif tail[0] == "history":
                self._json(store.history(run_id))
            elif tail[0] == "step" and len(tail) > 1:
                snap = self._int(tail[1])
                snap = store.snapshot(run_id, snap) if snap is not None else None
                self._json(snap or {"error": "not found"}, status=200 if snap else 404)
            elif tail[0] == "trace" and len(tail) > 2:
                step = self._int(tail[1])
                if step is None:
                    self._json({"error": "bad step"}, status=400)
                    return
                self._json(store.trace(run_id, step, unquote(tail[2])))
            elif tail[0] == "conversation" and len(tail) > 1:
                self._json(store.conversation(run_id, unquote(tail[1])))
            elif tail[0] == "kernels":
                self._json(store.kernels(run_id))
            else:
                self._json({"error": "not found"}, status=404)

        @staticmethod
        def _int(s):
            try:
                return int(s)
            except (TypeError, ValueError):
                return None

        # ------------------------------------------------------ launch/control
        def _launch(self):
            spec = self._body()
            if jobs is None:
                self._json({"error": "launching disabled"}, status=404)
                return
            try:
                run_id = jobs.launch(spec)
            except Exception as exc:  # bad spec / pool error -> 400, never crash
                self._json({"error": f"could not launch: {exc}"}, status=400)
                return
            self._json({"id": run_id, "status": jobs.status(run_id)}, status=201)

        def _control(self, run_id: str, action: str):
            if jobs is None:
                self._json({"error": "controls disabled"}, status=404)
                return
            if action not in ("pause", "resume", "stop"):
                self._json({"error": f"unknown action {action!r}"}, status=400)
                return
            if not store.exists(run_id) and jobs.status(run_id) is None:
                self._json({"error": "unknown run"}, status=404)
                return
            state = jobs.control(run_id, action)
            self._json({"state": _control_of(state)})

        # ---------------------------------------------------------------- SSE
        def _stream(self, run_id: str, parsed):
            if not store.exists(run_id):
                self._json({"error": "unknown run"}, status=404)
                return
            qs = parse_qs(parsed.query)
            try:
                sent = max(0, int(qs.get("from", ["0"])[0]))
            except ValueError:
                sent = 0

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            def write(event: str, data: str) -> None:
                self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode("utf-8"))
                self.wfile.flush()

            try:
                write("hello", json.dumps(store.meta(run_id), ensure_ascii=False))
                last_control = None
                last_beat = time.time()
                while True:
                    new = store.snapshots_from(run_id, sent)
                    for snap in new:
                        write("step", json.dumps(snap, ensure_ascii=False))
                        sent = snap["step"] + 1

                    state = store._status(run_id).get("state") or "done"
                    control = _control_of(state)
                    if control != last_control:
                        write("control", json.dumps({"state": control}))
                        last_control = control

                    now = time.time()
                    if now - last_beat >= HEARTBEAT_SECONDS:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last_beat = now

                    # A finished run never grows again; keep the socket open for
                    # inspection but poll lazily so we're not busy-waiting.
                    idle = state not in LIVE_STATES and not new
                    time.sleep(1.0 if idle else POLL_SECONDS)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    return Handler


def create_server(root, host: str = "0.0.0.0", port: int = 8000, jobs=None):
    """Bind and return the control-plane server (not yet serving).

    ``root`` is the ``runs/`` directory (str/Path or a ready :class:`RunStore`).
    Call ``server.serve_forever()`` (typically in a thread) to run it. With
    ``jobs=None`` the launcher/controls are disabled and this is a read surface.
    """
    store = root if isinstance(root, RunStore) else RunStore(root)
    httpd = _QuietThreadingHTTPServer((host, port), _make_handler(store, jobs))
    httpd.daemon_threads = True
    return httpd


def _print_urls(port: int) -> None:
    ip = _lan_ip()
    print("\n  Universe is live. Open it:")
    print(f"    - this machine : http://localhost:{port}")
    print(f"    - same wifi    : http://{ip}:{port}")
    print(f"    - anywhere     : http://<machine>.<tailnet>.ts.net:{port}  (Tailscale)\n")


def serve(root=None, host: str = "0.0.0.0", port: int = 8000, jobs=None) -> None:
    """Serve the control plane forever (blocking). CLI entry point."""
    # Default to the repository's canonical runs/ dir (AI-Playground/runs),
    # where gemma_world --save-dir and serve_gds shutdowns already write.
    root = Path(root) if root else Path(__file__).resolve().parents[2] / "runs"
    root.mkdir(parents=True, exist_ok=True)
    if jobs is None:
        # Default to a real JobManager so the launcher works from the CLI entry.
        try:
            from .jobs import JobManager
            jobs = JobManager(root)
        except Exception as exc:  # pragma: no cover - keep read surface working
            print(f"  (launcher unavailable: {exc})")
    httpd = create_server(root, host=host, port=port, jobs=jobs)
    _print_urls(port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.")
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Serve the Universe control plane.")
    p.add_argument("--runs", default="runs", help="runs directory (default: runs)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    serve(args.runs, host=args.host, port=args.port)
