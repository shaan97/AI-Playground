"""End-to-end: run_world.py CLI as a subprocess (docs/INTERFACES.md §CLI surfaces)."""
import json
import subprocess
import sys

from conftest import EXTERNAL_AGENT, REPO, read_log_records


def run_world(args, timeout=180):
    return subprocess.run(
        [sys.executable, "run_world.py"] + args,
        cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
    )


def test_mock_fresh_resume_inject_and_zero_ticks(tmp_path):
    d = str(tmp_path / "w")

    # fresh world
    p = run_world(["--mock", "--ticks", "3", "--names", "aria,bram",
                   "--data-dir", d])
    assert p.returncode == 0, p.stderr
    meta = json.loads((tmp_path / "w" / "meta.json").read_text())
    assert meta["tick"] == 3
    assert meta["agents"] == ["aria", "bram"]
    assert meta["genesis_done"] is True
    for name in ("aria", "bram"):
        ws = tmp_path / "w" / "agents" / name / "workspace"
        assert (ws / "identity.md").exists(), name
        assert (ws / "memory.md").exists(), name
    # mock agent index 0 is the builder
    assert (tmp_path / "w" / "objects" / "beacon").is_dir()

    # resume: same data dir continues from tick 3
    p = run_world(["--mock", "--ticks", "2", "--data-dir", d])
    assert p.returncode == 0, p.stderr
    meta = json.loads((tmp_path / "w" / "meta.json").read_text())
    assert meta["tick"] == 5
    assert meta["agents"] == ["aria", "bram"]  # persisted roster wins

    # --ticks 0 with --inject queues a system event without advancing time
    p = run_world(["--mock", "--ticks", "0",
                   "--inject", "operator: aurora tonight",
                   "--inject-to", "all", "--data-dir", d])
    assert p.returncode == 0, p.stderr
    meta = json.loads((tmp_path / "w" / "meta.json").read_text())
    assert meta["tick"] == 5  # 0 ticks: time did not advance
    recs = read_log_records(tmp_path / "w")
    assert any(r.get("kind") == "system" and
               "aurora tonight" in json.dumps(r.get("payload", {}))
               for r in recs)
    # the injection sits undelivered in the persisted inboxes
    assert "aurora tonight" in json.dumps(meta["inboxes"])

    # ...and survives to the next run, where agents perceive it
    mem_before = (tmp_path / "w" / "agents" / "bram" / "workspace" / "memory.md").read_text()
    p = run_world(["--mock", "--ticks", "1", "--data-dir", d])
    assert p.returncode == 0, p.stderr
    mem_after = (tmp_path / "w" / "agents" / "bram" / "workspace" / "memory.md").read_text()
    assert len(mem_after) > len(mem_before)


def test_agent_cmd_external_harness(tmp_path):
    d = str(tmp_path / "ext")
    cmd = "%s %s" % (sys.executable, EXTERNAL_AGENT)
    p = run_world(["--agent-cmd", cmd, "--ticks", "2", "--names", "solo",
                   "--data-dir", d])
    assert p.returncode == 0, p.stderr
    ws = tmp_path / "ext" / "agents" / "solo" / "workspace"
    assert (ws / "identity.md").exists()
    assert (ws / "memory.md").exists()
    assert (ws / "memory.md").read_text().strip()
    # the reference harness creates a guestbook at genesis
    assert (tmp_path / "ext" / "objects" / "guestbook").is_dir()


def test_config_mixed_mock_and_process_world(tmp_path):
    d = str(tmp_path / "mixed")
    config = [
        {"name": "mocky", "harness": "mock", "builder": True},
        {"name": "proc", "harness": "process",
         "command": "%s %s" % (sys.executable, EXTERNAL_AGENT)},
    ]
    cfg_path = tmp_path / "agents.json"
    cfg_path.write_text(json.dumps(config))
    p = run_world(["--config", str(cfg_path), "--ticks", "2", "--data-dir", d])
    assert p.returncode == 0, p.stderr
    meta = json.loads((tmp_path / "mixed" / "meta.json").read_text())
    assert meta["agents"] == ["mocky", "proc"]
    for name in ("mocky", "proc"):
        ws = tmp_path / "mixed" / "agents" / name / "workspace"
        assert (ws / "identity.md").exists(), name
        assert (ws / "memory.md").exists(), name
    # mock builder made its beacon; the process harness made its guestbook
    assert (tmp_path / "mixed" / "objects" / "beacon").is_dir()
    assert (tmp_path / "mixed" / "objects" / "guestbook").is_dir()
