"""Unit tests for world.agent.AgentRuntime.dispatch per docs/INTERFACES.md §world.agent."""
from conftest import none_factory

from world.kernel import World


def runtime(tmp_path, names=("aria", "bram")):
    w = World(tmp_path, none_factory, list(names), quiet=True)
    return w, w.agents["aria"]


def workspace(tmp_path, name="aria"):
    return tmp_path / "agents" / name / "workspace"


# ------------------------------------------------------------------ general

def test_unknown_action_is_error_string(tmp_path):
    _, rt = runtime(tmp_path)
    r = rt.dispatch("fly_to_moon", {})
    assert isinstance(r, str)
    assert r.startswith("error:")


def test_dispatch_never_raises_on_bad_input(tmp_path):
    _, rt = runtime(tmp_path)
    # missing required fields should come back as error strings, not exceptions
    for action, bad_input in [
        ("read_file", {}),
        ("write_file", {}),
        ("send_message", {}),
        ("inspect_object", {}),
    ]:
        r = rt.dispatch(action, bad_input)
        assert isinstance(r, str), action
        assert r.startswith("error:"), (action, r)


def test_result_truncated_at_8000_chars(tmp_path):
    _, rt = runtime(tmp_path)
    content = "x" * 20000
    assert not rt.dispatch("write_file", {"path": "big.txt",
                                          "content": content}).startswith("error:")
    r = rt.dispatch("read_file", {"path": "big.txt"})
    assert len(r) < 20000           # actually truncated
    assert len(r) <= 8200           # ~8000 plus a marker
    assert "truncat" in r.lower()   # carries a truncation marker


def test_write_file_over_512k_chars_is_error(tmp_path):
    _, rt = runtime(tmp_path)
    r = rt.dispatch("write_file", {"path": "huge.txt", "content": "y" * 512_001})
    assert r.startswith("error:")
    assert not (workspace(tmp_path) / "huge.txt").exists()
    # boundary: exactly 512,000 chars is allowed
    r = rt.dispatch("write_file", {"path": "edge.txt", "content": "y" * 512_000})
    assert not r.startswith("error:")


# ---------------------------------------------------------------- file jail

def test_paths_escaping_workspace_are_errors(tmp_path):
    _, rt = runtime(tmp_path)
    for path in ("../outside.txt", "../../etc/passwd", "a/../../b.txt"):
        assert rt.dispatch("write_file", {"path": path, "content": "x"}).startswith("error:"), path
        assert rt.dispatch("read_file", {"path": path}).startswith("error:"), path
    # absolute path outside the workspace
    assert rt.dispatch("read_file", {"path": "/etc/passwd"}).startswith("error:")
    # nothing leaked outside
    assert not (tmp_path / "agents" / "aria" / "outside.txt").exists()


def test_write_creates_parent_dirs_and_read_round_trips(tmp_path):
    _, rt = runtime(tmp_path)
    r = rt.dispatch("write_file", {"path": "notes/deep/plan.md", "content": "step 1"})
    assert not r.startswith("error:")
    assert (workspace(tmp_path) / "notes" / "deep" / "plan.md").read_text() == "step 1"
    r = rt.dispatch("read_file", {"path": "notes/deep/plan.md"})
    assert "step 1" in r


def test_read_missing_file_is_error(tmp_path):
    _, rt = runtime(tmp_path)
    assert rt.dispatch("read_file", {"path": "nope.txt"}).startswith("error:")


def test_list_files_empty_then_relative_paths(tmp_path):
    _, rt = runtime(tmp_path)
    assert rt.dispatch("list_files", {}) == "(empty)"
    rt.dispatch("write_file", {"path": "a.txt", "content": "1"})
    rt.dispatch("write_file", {"path": "sub/b.txt", "content": "2"})
    r = rt.dispatch("list_files", {})
    lines = r.splitlines()
    assert "a.txt" in lines
    assert any(l.replace("\\", "/") == "sub/b.txt" for l in lines)
    # relative paths only
    assert all(not l.startswith("/") for l in lines)


# ----------------------------------------------------- world action delegacy

def test_world_actions_delegate_with_dispatching_agent_as_actor(tmp_path):
    w, rt = runtime(tmp_path)
    r = rt.dispatch("create_object", {"name": "totem", "description": "a totem"})
    assert not r.startswith("error:")
    assert w.objects["totem"].creator == "aria"

    r = rt.dispatch("observe_world", {})
    assert not r.startswith("error:")
    assert "totem" in r

    r = rt.dispatch("inspect_object", {"name": "totem"})
    assert "totem" in r and not r.startswith("error:")

    r = rt.dispatch("send_message", {"to": "bram", "text": "made a totem"})
    assert not r.startswith("error:")
    assert any(e.source == "aria" and e.payload.get("text") == "made a totem"
               for e in w.inboxes["bram"])

    r = rt.dispatch("set_subscriptions", {"kinds": ["message", "system"]})
    assert not r.startswith("error:")
    assert set(w.subscriptions["aria"]) == {"message", "system"}

    # error: passthrough from the kernel
    r = rt.dispatch("inspect_object", {"name": "no-such-thing"})
    assert r.startswith("error:")
