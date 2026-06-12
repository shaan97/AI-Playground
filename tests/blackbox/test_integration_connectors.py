"""Integration: ProcessConnector contracts and the reference external harness
(docs/INTERFACES.md §world.connectors, PROTOCOL.md)."""
import sys

from conftest import EXTERNAL_AGENT, none_factory

from world import protocol
from world.connectors import ProcessConnector
from world.kernel import World


def make_wake(tmp_path, name="aria"):
    w = World(tmp_path, none_factory, [name], quiet=True)
    return protocol.build_wake(w.agents[name], [], w)


# --------------------------------------------- raw ProcessConnector contracts

def test_process_connector_speaks_protocol_and_returns_note(tmp_path):
    script = (
        "import json, sys\n"
        "wake = json.loads(sys.stdin.readline())\n"
        "print('this is not json and must be ignored', flush=True)\n"
        "print(json.dumps({'type': 'action', 'name': 'observe_world',"
        " 'input': {}, 'id': 'a1'}), flush=True)\n"
        "res = json.loads(sys.stdin.readline())\n"
        "note = 'saw=' + res['content']\n"
        "print(json.dumps({'type': 'end_turn', 'note': note}), flush=True)\n"
    )
    calls = []

    def dispatch(name, inp):
        calls.append((name, inp))
        return "DIGEST-42"

    conn = ProcessConnector([sys.executable, "-c", script], turn_timeout=30)
    note = conn.take_turn(make_wake(tmp_path), dispatch)
    assert calls == [("observe_world", {})]
    assert note == "saw=DIGEST-42"


def test_process_connector_sets_env_vars(tmp_path):
    script = (
        "import json, os, sys\n"
        "wake = json.loads(sys.stdin.readline())\n"
        "note = '|'.join([os.environ['WORLD_AGENT_NAME'],"
        " os.environ['WORLD_WORKSPACE'], os.environ['WORLD_TICK']])\n"
        "print(json.dumps({'type': 'end_turn', 'note': note}), flush=True)\n"
    )
    conn = ProcessConnector([sys.executable, "-c", script], turn_timeout=30)
    wake = make_wake(tmp_path, "aria")
    note = conn.take_turn(wake, lambda n, i: "ok")
    name, workspace, tick = note.split("|")
    assert name == "aria"
    assert workspace == wake["workspace"]
    assert tick == str(wake["tick"])


def test_process_connector_eof_without_end_turn_yields_note(tmp_path):
    script = "import sys\nsys.stdin.readline()\n"  # read wake, exit silently
    conn = ProcessConnector([sys.executable, "-c", script], turn_timeout=30)
    note = conn.take_turn(make_wake(tmp_path), lambda n, i: "ok")
    assert isinstance(note, str)
    assert note  # a note saying so — non-empty


def test_process_connector_timeout_kills_and_mentions_timeout(tmp_path):
    script = "import sys, time\nsys.stdin.readline()\ntime.sleep(60)\n"
    conn = ProcessConnector([sys.executable, "-c", script], turn_timeout=2)
    note = conn.take_turn(make_wake(tmp_path), lambda n, i: "ok")
    assert isinstance(note, str)
    assert "timeout" in note.lower() or "timed out" in note.lower()


def test_process_connector_accepts_string_command(tmp_path):
    cmd = '%s -c "import json,sys; sys.stdin.readline(); ' \
          'print(json.dumps({\'type\': \'end_turn\', \'note\': \'str-cmd\'}), flush=True)"' \
          % sys.executable
    conn = ProcessConnector(cmd, turn_timeout=30)
    note = conn.take_turn(make_wake(tmp_path), lambda n, i: "ok")
    assert note == "str-cmd"


# ------------------------------------------- external harness inside a world

def external_factory(index, name):
    return ProcessConnector([sys.executable, str(EXTERNAL_AGENT)], turn_timeout=60)


def test_external_agent_harness_in_lockstep_world(tmp_path):
    w = World(tmp_path, external_factory, ["aria", "bram"], quiet=True)
    w.run(2)
    # genesis: identity.md written, guestbook object created
    for name in ("aria", "bram"):
        ws = tmp_path / "agents" / name / "workspace"
        assert (ws / "identity.md").exists(), name
        # always appends a line to memory.md
        assert (ws / "memory.md").exists(), name
        assert (ws / "memory.md").read_text().strip(), name
    assert "guestbook" in w.objects
    # genesis greeting broadcasts mean later wakes carry message events,
    # so agents sign the guestbook via its on_interact
    gb = w.objects["guestbook"]
    assert isinstance(gb.state, dict)
    assert any(gb_entries for gb_entries in gb.state.values()), \
        "guestbook should have been signed after message wakes"
