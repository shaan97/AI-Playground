"""Shared helpers for the black-box suite.

All tests here are written purely against docs/INTERFACES.md and PROTOCOL.md.
No implementation source was consulted.
"""
import json
import pathlib
import socket
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

EXTERNAL_AGENT = REPO / "examples" / "external_agent.py"


def none_factory(index, name):
    """connector_factory that supplies no local brain (server-mode style)."""
    return None


class RecordingConnector:
    """Minimal Connector-protocol implementation for routing tests."""

    def __init__(self, note="noted"):
        self.wakes = []
        self.note = note

    def take_turn(self, wake, dispatch):
        self.wakes.append(wake)
        return self.note


def free_port():
    """Pick a free TCP port via bind-then-close (for subprocess servers)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def http(method, url, token=None, body=None, raw_body=None, timeout=30):
    """One JSON-ish HTTP request. Returns (status, parsed_body_or_text_or_None)."""
    req = urllib.request.Request(url, method=method)
    if token is not None:
        req.add_header("Authorization", "Bearer " + token)
    data = None
    if raw_body is not None:
        data = raw_body.encode()
        req.add_header("Content-Type", "application/json")
    elif body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            text = resp.read().decode()
            status = resp.status
    except urllib.error.HTTPError as exc:
        text = exc.read().decode()
        status = exc.code
    if not text:
        return status, None
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def read_log_records(root):
    """Parse log/events.jsonl into a list of dicts."""
    path = pathlib.Path(root) / "log" / "events.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records
