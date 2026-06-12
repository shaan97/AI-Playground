"""Integration: lockstep World.run with MockConnectors.

Covers genesis, memory file conventions, and the builder's beacon lifecycle
(per docs/INTERFACES.md §world.connectors MockConnector contract).
"""
import json

from conftest import read_log_records

from world.connectors import MockConnector
from world.kernel import World


def mock_factory(index, name):
    return MockConnector(builder=(index == 0))


def test_mock_world_genesis_and_memory_files(tmp_path):
    w = World(tmp_path, mock_factory, ["aria", "bram"], quiet=True)
    w.run(2)
    for name in ("aria", "bram"):
        ws = tmp_path / "agents" / name / "workspace"
        assert (ws / "identity.md").exists(), name
        assert (ws / "memory.md").exists(), name
        assert (ws / "identity.md").read_text().strip()
    # later wakes append Turn lines to memory.md
    mem = (tmp_path / "agents" / "aria" / "workspace" / "memory.md").read_text()
    assert "Turn" in mem


def test_mock_first_wake_broadcasts_a_greeting(tmp_path):
    w = World(tmp_path, mock_factory, ["aria", "bram"], quiet=True)
    w.run(1)
    recs = read_log_records(tmp_path)
    msgs = [r for r in recs if r.get("kind") == "message" and r.get("to") == "all"]
    sources = {m.get("source") for m in msgs}
    assert "aria" in sources and "bram" in sources


def test_builder_creates_beacon_and_it_pulses_and_gets_touched(tmp_path):
    w = World(tmp_path, mock_factory, ["aria", "bram"], quiet=True)
    w.run(5)
    # builder (index 0 = aria) created the beacon
    assert "beacon" in w.objects
    beacon = w.objects["beacon"]
    assert beacon.creator == "aria"
    # beacon's on_tick broadcast {"pulse": N} on even ticks
    recs = read_log_records(tmp_path)
    pulses = [r for r in recs
              if r.get("kind") == "object" and r.get("source") == "beacon"
              and "pulse" in r.get("payload", {})]
    assert pulses, "expected at least one pulse event in the log"
    assert all(r["tick"] % 2 == 0 for r in pulses)
    # a non-builder perceiving a pulse interacts; touches counted in state
    assert beacon.state.get("touches", 0) >= 1


def test_mock_world_advances_tick_and_seq(tmp_path):
    w = World(tmp_path, mock_factory, ["aria", "bram"], quiet=True)
    w.run(3)
    assert w.tick == 3
    assert w.seq > 0
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["tick"] == 3
    assert meta["seq"] == w.seq
    assert meta["agents"] == ["aria", "bram"]
    assert meta["genesis_done"] is True
