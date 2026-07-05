"""A zero-dependency HTTP + SSE server that serves the world viewer.

Stdlib only (`http.server`), matching the substrate's no-deps ethos. It exposes a
small JSON API over a `ViewerHub` plus a single-page UI, and a Server-Sent-Events
stream that pushes each new step to connected phones in real time.

Endpoints:
    GET /                       the single-page viewer (static/index.html)
    GET /api/meta               {count, latest, agents, registry}
    GET /api/history            [snapshot, ...]  (light: states + arcs + traced)
    GET /api/step/<i>           one snapshot
    GET /api/trace/<i>/<vertex> the agent's turn transcript for that step
    GET /api/stream             SSE: `hello` (meta) then a `step` event per step

Use `serve_gds(gds, steps=..., delay=...)` for the batteries-included path: it
instruments agents, starts the server in a background thread, prints the LAN /
Tailscale URLs, then runs the step loop so you can watch it live.
"""

from __future__ import annotations

import json
import queue
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .control import RunControl
from .hub import ViewerHub

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _make_handler(hub: ViewerHub, control: RunControl | None = None, on_shutdown=None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        # --- helpers -------------------------------------------------------
        def _send_json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str):
            try:
                body = path.read_bytes()
            except OSError:
                self._send_json({"error": "not found"}, status=404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # quiet by default
            pass

        # --- routing -------------------------------------------------------
        def do_GET(self):
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path == "/":
                self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            elif path == "/api/meta":
                self._send_json(hub.meta())
            elif path == "/api/history":
                self._send_json(hub.history())
            elif path.startswith("/api/step/"):
                try:
                    i = int(path.rsplit("/", 1)[1])
                except ValueError:
                    self._send_json({"error": "bad step"}, status=400)
                    return
                snap = hub.snapshot(i)
                self._send_json(snap or {"error": "not found"}, status=200 if snap else 404)
            elif path.startswith("/api/trace/"):
                parts = path[len("/api/trace/"):].split("/", 1)
                if len(parts) != 2:
                    self._send_json({"error": "bad trace path"}, status=400)
                    return
                try:
                    i = int(parts[0])
                except ValueError:
                    self._send_json({"error": "bad step"}, status=400)
                    return
                self._send_json(hub.trace(i, unquote(parts[1])))
            elif path == "/api/stream":
                self._stream()
            else:
                self._send_json({"error": "not found"}, status=404)

        # --- control (operator intervention) -------------------------------
        def do_POST(self):
            path = self.path.split("?", 1)[0].rstrip("/")
            # Drain any request body so the connection stays clean for keep-alive.
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            if not path.startswith("/api/control/"):
                self._send_json({"error": "not found"}, status=404)
                return
            if control is None:
                self._send_json({"error": "controls disabled"}, status=404)
                return
            action = path.rsplit("/", 1)[1]
            if action == "shutdown":
                if on_shutdown is None:
                    self._send_json({"error": "shutdown disabled"}, status=404)
                    return
                # Reply *before* the process tears down so the client gets ack.
                self._send_json({"state": "shutting_down"})
                on_shutdown()
                return
            actions = {"pause": control.pause, "resume": control.resume, "stop": control.stop}
            fn = actions.get(action)
            if fn is None:
                self._send_json({"error": f"unknown action {action!r}"}, status=400)
                return
            self._send_json({"state": fn()})

        # --- SSE -----------------------------------------------------------
        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = hub.subscribe()
            try:
                hello = json.dumps(hub.meta(), ensure_ascii=False)
                self.wfile.write(f"event: hello\ndata: {hello}\n\n".encode("utf-8"))
                self.wfile.flush()
                while True:
                    try:
                        event, payload = q.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")  # heartbeat
                        self.wfile.flush()
                        continue
                    self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hub.unsubscribe(q)

    return Handler


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that swallows the connection-reset tracebacks a normal
    `http.server` prints when an SSE client disconnects — routine on phones that
    lock the screen or background the tab, not an error worth a stack trace."""

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def start_server(hub: ViewerHub, host: str = "0.0.0.0", port: int = 8000,
                 control: RunControl | None = None, on_shutdown=None):
    """Start the viewer HTTP server in a daemon thread; return the server."""
    httpd = _QuietThreadingHTTPServer((host, port), _make_handler(hub, control, on_shutdown))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, name="viewer-http", daemon=True).start()
    return httpd


def _lan_ip() -> str:
    """Best-effort primary LAN IP (no traffic actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _print_urls(port: int) -> None:
    ip = _lan_ip()
    print("\n  Universe viewer is live. Open on your phone:")
    print(f"    - this machine : http://localhost:{port}")
    print(f"    - same wifi    : http://{ip}:{port}")
    print(f"    - anywhere     : http://<your-machine>.<tailnet>.ts.net:{port}")
    print("                     (run `tailscale ip -4` / use MagicDNS; phone on the")
    print("                      same tailnet, then this works over cellular too)\n")


def serve_gds(
    gds,
    *,
    steps: int | None = None,
    delay: float = 1.0,
    host: str = "0.0.0.0",
    port: int = 8000,
    hub: ViewerHub | None = None,
    save_dir: str | None = None,
) -> ViewerHub:
    """Instrument `gds`, serve the viewer, and run the step loop live.

    Captures the genesis configuration, then steps `steps` times (or forever if
    `steps` is None), pausing `delay` seconds between steps so the evolution is
    watchable on a phone.

    Halting (remote Stop, finite `steps`, or Ctrl-C) freezes the world but keeps
    the server up for inspection. A remote **Shutdown** additionally saves a
    resumable snapshot and exits the process. If `save_dir` is given, the run is
    saved there on every halt; otherwise Shutdown saves to ``runs/<timestamp>``.
    Returns the hub.
    """
    hub = hub or ViewerHub()
    hub.instrument(gds)
    control = RunControl(on_change=hub.publish_control)
    shutdown = threading.Event()

    def _save() -> str | None:
        from .persistence import save_run
        target = save_dir or f"runs/run-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            path = save_run(gds, target)
            hub.save_traces(target)  # persist agent reasoning alongside the trajectory
            print(f"  Saved run -> {path}  (resume with --resume {path})")
            return str(path)
        except Exception as exc:  # saving must never crash shutdown
            print(f"  WARN: could not save run: {exc!r}")
            return None

    def _on_shutdown() -> None:
        control.stop()       # halt the loop
        shutdown.set()       # release the idle wait → process exits

    start_server(hub, host=host, port=port, control=control, on_shutdown=_on_shutdown)
    _print_urls(port)

    hub.publish(gds)  # genesis (step 0)
    stopped = False
    try:
        t = 0
        while steps is None or t < steps:
            control.wait_while_paused()       # block here while paused
            if control.should_stop():         # remote stop → leave the loop
                stopped = True
                break
            gds.step()
            hub.publish(gds)
            t += 1
            control.sleep(delay)              # inter-step delay, interruptible
    except KeyboardInterrupt:
        stopped = True
        print("\n  stopped (local).")
    else:
        if stopped:
            print(f"\n  Stopped remotely at {len(hub.history()) - 1} steps.")
        else:
            print(f"\n  Done — {len(hub.history())} configurations.")

    # Reflect the halted run-state, then idle so the final world stays inspectable
    # — until a remote Shutdown (or Ctrl-C) exits. Every exit path saves a
    # resumable snapshot exactly once.
    control.stop()
    saved = {"done": False}

    def _save_once() -> None:
        if not saved["done"]:
            _save()
            saved["done"] = True

    if save_dir is not None:
        _save_once()  # save-on-halt when a target was given
    print("  Server still serving for inspection. Ctrl-C — or remote Shutdown — to exit.")
    try:
        shutdown.wait()
    except KeyboardInterrupt:
        pass
    _save_once()      # guarantee a resumable snapshot on the way out
    if shutdown.is_set():
        print("  Shutting down.")
    return hub
