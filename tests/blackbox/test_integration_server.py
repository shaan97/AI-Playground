"""Integration: WorldServer + WorldClient over real HTTP on an ephemeral port
(docs/INTERFACES.md §world.server, §world.client; PROTOCOL.md §Remote mode)."""
import contextlib
import json

from conftest import http, none_factory

from world.client import WorldClient
from world.connectors import MockConnector
from world.kernel import World
from world.server import WorldServer, load_or_create_tokens

NAMES = ["aria", "bram"]
TOKENS = {"admin": "admin-secret", "agents": {"aria": "tok-aria", "bram": "tok-bram"}}


@contextlib.contextmanager
def server(tmp_path, rate_limit=1000, names=NAMES, tokens=TOKENS):
    world = World(tmp_path, none_factory, list(names), quiet=True)
    srv = WorldServer(world, tokens, host="127.0.0.1", port=0,
                      tick_interval=0, rate_limit=rate_limit)
    srv.start()
    try:
        yield world, srv, "http://%s:%s" % (srv.host, srv.port)
    finally:
        srv.shutdown()


def ack(url, agent, cursor, note="ok"):
    status, body = http("POST", url + "/agents/%s/turns" % agent,
                        token=TOKENS["agents"][agent],
                        body={"note": note, "cursor": cursor})
    assert status == 200, body
    return body


def drain(url, agent):
    """Consume whatever is pending in an agent's inbox."""
    status, body = http("GET", url + "/agents/%s/wake?wait=2" % agent,
                        token=TOKENS["agents"][agent])
    if status == 200:
        ack(url, agent, body["cursor"])
    return status


# ------------------------------------------------------------- tokens helper

def test_load_or_create_tokens(tmp_path):
    toks = load_or_create_tokens(tmp_path, ["aria", "bram"])
    assert set(toks) == {"admin", "agents"}
    assert isinstance(toks["admin"], str) and toks["admin"]
    assert set(toks["agents"]) == {"aria", "bram"}
    on_disk = json.loads((tmp_path / "tokens.json").read_text())
    assert on_disk == toks
    # existing tokens preserved, new agents extended
    toks2 = load_or_create_tokens(tmp_path, ["aria", "bram", "cleo"])
    assert toks2["admin"] == toks["admin"]
    assert toks2["agents"]["aria"] == toks["agents"]["aria"]
    assert "cleo" in toks2["agents"]


# --------------------------------------------------------------------- auth

def test_auth_and_routing(tmp_path):
    with server(tmp_path) as (world, srv, url):
        # missing token -> 403 with a JSON error body
        status, body = http("GET", url + "/world")
        assert status == 403
        assert isinstance(body, dict)
        # wrong token -> 403
        status, _ = http("GET", url + "/world", token="nope")
        assert status == 403
        # GET /world accepts any valid token (agent or admin)
        for tok in (TOKENS["agents"]["aria"], TOKENS["admin"]):
            status, body = http("GET", url + "/world", token=tok)
            assert status == 200
            assert set(body) >= {"tick", "agents", "digest"}
            assert body["agents"] == NAMES
        # an agent's token is valid only for that agent's endpoints
        status, _ = http("GET", url + "/agents/bram/wake?wait=1",
                         token=TOKENS["agents"]["aria"])
        assert status == 403
        # agent token cannot reach /admin/*
        status, _ = http("POST", url + "/admin/step",
                         token=TOKENS["agents"]["aria"], body={})
        assert status == 403
        # admin token only valid for /admin/*
        status, _ = http("GET", url + "/agents/aria/wake?wait=1",
                         token=TOKENS["admin"])
        assert status == 403
        # unknown agent name in path -> 404
        status, _ = http("GET", url + "/agents/ghost/wake?wait=1",
                         token=TOKENS["agents"]["aria"])
        assert status == 404
        # unknown route -> 404
        status, _ = http("GET", url + "/definitely/not/a/route",
                         token=TOKENS["admin"])
        assert status == 404


# ------------------------------------------------- wake / ack / redelivery

def test_wake_long_poll_redelivery_and_ack(tmp_path):
    with server(tmp_path) as (world, srv, url):
        # start() ran genesis -> inbox non-empty -> immediate 200
        status, wake1 = http("GET", url + "/agents/aria/wake?wait=5",
                             token=TOKENS["agents"]["aria"])
        assert status == 200
        assert wake1["type"] == "wake"
        assert isinstance(wake1["cursor"], int)
        kinds = [e["kind"] for e in wake1["events"]]
        assert "genesis" in kinds
        seqs1 = [e["seq"] for e in wake1["events"]]
        assert wake1["cursor"] == max(seqs1)
        assert len(wake1["events_text"]) == len(wake1["events"])

        # at-least-once: not acked, so the same events come again
        status, wake2 = http("GET", url + "/agents/aria/wake?wait=5",
                             token=TOKENS["agents"]["aria"])
        assert status == 200
        assert set(seqs1) <= {e["seq"] for e in wake2["events"]}

        # ack consumes them
        ack(url, "aria", wake2["cursor"], note="genesis processed")
        status, body = http("GET", url + "/agents/aria/wake?wait=2",
                            token=TOKENS["agents"]["aria"])
        assert status == 204
        assert body is None  # 204 carries no body


# ---------------------------------------------------------- actions endpoint

def test_actions_endpoint_success_and_error_passthrough(tmp_path):
    with server(tmp_path) as (world, srv, url):
        status, body = http("POST", url + "/agents/aria/actions",
                            token=TOKENS["agents"]["aria"],
                            body={"name": "send_message",
                                  "input": {"to": "all", "text": "hello http"}})
        assert status == 200
        assert isinstance(body["content"], str)
        assert not body["content"].startswith("error:")
        # the message reaches bram's queue
        status, wake = http("GET", url + "/agents/bram/wake?wait=5",
                            token=TOKENS["agents"]["bram"])
        assert status == 200
        assert any(e["kind"] == "message" and e["payload"].get("text") == "hello http"
                   for e in wake["events"])
        # action failure is NOT an HTTP error: 200 with error: content
        status, body = http("POST", url + "/agents/aria/actions",
                            token=TOKENS["agents"]["aria"],
                            body={"name": "inspect_object",
                                  "input": {"name": "no-such-object"}})
        assert status == 200
        assert body["content"].startswith("error:")


def test_malformed_json_body_is_400(tmp_path):
    with server(tmp_path) as (world, srv, url):
        status, _ = http("POST", url + "/agents/aria/actions",
                         token=TOKENS["agents"]["aria"],
                         raw_body="{this is not json")
        assert status == 400


def test_rate_limit_429(tmp_path):
    with server(tmp_path, rate_limit=3) as (world, srv, url):
        statuses = []
        for i in range(4):
            status, _ = http("POST", url + "/agents/aria/actions",
                             token=TOKENS["agents"]["aria"],
                             body={"name": "observe_world", "input": {}})
            statuses.append(status)
        assert statuses[:3] == [200, 200, 200]
        assert statuses[3] == 429
        # the other agent has its own budget
        status, _ = http("POST", url + "/agents/bram/actions",
                         token=TOKENS["agents"]["bram"],
                         body={"name": "observe_world", "input": {}})
        assert status == 200


# ----------------------------------------------------------------- admin api

def test_admin_step_and_inject(tmp_path):
    with server(tmp_path) as (world, srv, url):
        drain(url, "aria")
        status, body = http("POST", url + "/admin/step", token=TOKENS["admin"], body={})
        assert status == 200
        assert body == {"tick": 1}
        status, body = http("POST", url + "/admin/inject", token=TOKENS["admin"],
                            body={"text": "operator waves", "to": "aria"})
        assert status == 200
        assert body == {"ok": True}
        status, wake = http("GET", url + "/agents/aria/wake?wait=5",
                            token=TOKENS["agents"]["aria"])
        assert status == 200
        kinds = [e["kind"] for e in wake["events"]]
        assert "tick" in kinds
        assert any(e["kind"] == "system" and "operator waves" in
                   json.dumps(e["payload"]) for e in wake["events"])
        with srv.lock:
            assert world.tick == 1


# ----------------------------------------- subscriptions over HTTP semantics

def test_subscriptions_changed_via_http_affect_tick_delivery(tmp_path):
    with server(tmp_path) as (world, srv, url):
        drain(url, "aria")
        status, body = http("POST", url + "/agents/aria/actions",
                            token=TOKENS["agents"]["aria"],
                            body={"name": "set_subscriptions",
                                  "input": {"kinds": ["message"]}})
        assert status == 200
        assert not body["content"].startswith("error:")
        # a tick broadcast no longer wakes aria
        status, _ = http("POST", url + "/admin/step", token=TOKENS["admin"], body={})
        assert status == 200
        status, _ = http("GET", url + "/agents/aria/wake?wait=2",
                         token=TOKENS["agents"]["aria"])
        assert status == 204
        # but a direct event bypasses the filter
        status, _ = http("POST", url + "/admin/inject", token=TOKENS["admin"],
                         body={"text": "psst", "to": "aria"})
        assert status == 200
        status, wake = http("GET", url + "/agents/aria/wake?wait=5",
                            token=TOKENS["agents"]["aria"])
        assert status == 200
        assert any(e["kind"] == "system" for e in wake["events"])


# -------------------------------------------------------------- WorldClient

def test_world_client_runs_mock_connector_and_acks(tmp_path):
    with server(tmp_path) as (world, srv, url):
        client = WorldClient(url, "aria", TOKENS["agents"]["aria"],
                             MockConnector(), wait=5, quiet=True)
        n = client.run(max_wakes=1)
        assert n == 1
        # mock first wake wrote identity/memory into the server-side workspace
        ws = tmp_path / "agents" / "aria" / "workspace"
        assert (ws / "identity.md").exists()
        assert (ws / "memory.md").exists()
        # the turn ack consumed the inbox
        status, _ = http("GET", url + "/agents/aria/wake?wait=2",
                         token=TOKENS["agents"]["aria"])
        assert status == 204
        # client.dispatch proxies one action over HTTP
        r = client.dispatch("send_message", {"to": "all", "text": "from client"})
        assert isinstance(r, str)
        assert not r.startswith("error:")


def test_world_client_dispatch_maps_http_errors_to_error_strings(tmp_path):
    with server(tmp_path) as (world, srv, url):
        bad = WorldClient(url, "aria", "wrong-token", MockConnector(),
                          wait=2, quiet=True)
        r = bad.dispatch("observe_world", {})
        assert isinstance(r, str)
        assert r.startswith("error:")
