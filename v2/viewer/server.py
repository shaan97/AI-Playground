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
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .hub import ViewerHub

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _make_handler(hub: ViewerHub):
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
                        payload = q.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")  # heartbeat
                        self.wfile.flush()
                        continue
                    self.wfile.write(f"event: step\ndata: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hub.unsubscribe(q)

    return Handler


def start_server(hub: ViewerHub, host: str = "0.0.0.0", port: int = 8000):
    """Start the viewer HTTP server in a daemon thread; return the server."""
    httpd = ThreadingHTTPServer((host, port), _make_handler(hub))
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
    print(f"    • this machine : http://localhost:{port}")
    print(f"    • same wifi    : http://{ip}:{port}")
    print(f"    • anywhere     : http://<your-machine>.<tailnet>.ts.net:{port}")
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
) -> ViewerHub:
    """Instrument `gds`, serve the viewer, and run the step loop live.

    Captures the genesis configuration, then steps `steps` times (or forever if
    `steps` is None), pausing `delay` seconds between steps so the evolution is
    watchable on a phone. Returns the hub.
    """
    hub = hub or ViewerHub()
    hub.instrument(gds)
    start_server(hub, host=host, port=port)
    _print_urls(port)

    hub.publish(gds)  # genesis (step 0)
    try:
        t = 0
        while steps is None or t < steps:
            gds.step()
            hub.publish(gds)
            t += 1
            if delay:
                time.sleep(delay)
    except KeyboardInterrupt:
        print("\n  stopped. (server still up — Ctrl-C again to exit)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    else:
        print(f"\n  Done — {len(hub.history())} configurations. Server still serving; "
              "Ctrl-C to exit.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    return hub
