"""Unit tests for world.sandbox.run_hook per docs/INTERFACES.md §world.sandbox."""
from world.sandbox import run_hook


def tick(code, state=None, **kw):
    return run_hook(code, "on_tick", dict(state or {}), world={"tick": 1}, **kw)


# ---------------------------------------------------------------- basic runs

def test_state_mutation_in_place_is_persisted():
    code = "def on_tick(state, world, emit):\n    state['n'] = state.get('n', 0) + 1\n"
    res = tick(code, {"n": 4})
    assert res.ok is True
    assert res.missing is False
    assert res.error is None
    assert res.state == {"n": 5}


def test_returned_dict_replaces_state():
    code = "def on_tick(state, world, emit):\n    return {'fresh': True}\n"
    res = tick(code, {"old": 1})
    assert res.ok is True
    assert res.state == {"fresh": True}


def test_missing_hook_is_flagged():
    code = "def on_interact(state, action, source, emit):\n    return 'hi'\n"
    res = tick(code, {"a": 1})
    assert res.missing is True


def test_emit_collects_payload_and_to():
    code = (
        "def on_tick(state, world, emit):\n"
        "    emit({'x': 1}, to='aria')\n"
        "    emit({'y': 2})\n"
    )
    res = tick(code)
    assert res.ok is True
    assert res.emitted == [
        {"payload": {"x": 1}, "to": "aria"},
        {"payload": {"y": 2}, "to": "all"},
    ]


def test_on_interact_result_and_args():
    code = (
        "def on_interact(state, action, source, emit):\n"
        "    state['last'] = action\n"
        "    return {'echo': action, 'from': source}\n"
    )
    res = run_hook(code, "on_interact", {}, action="poke", source="bram")
    assert res.ok is True
    assert res.result == {"echo": "poke", "from": "bram"}
    assert res.state == {"last": "poke"}


def test_world_snapshot_is_visible_to_on_tick():
    code = "def on_tick(state, world, emit):\n    state['t'] = world['tick']\n"
    res = run_hook(code, "on_tick", {}, world={"tick": 11, "agents": [], "objects": {}})
    assert res.ok is True
    assert res.state == {"t": 11}


# ---------------------------------------------------------- failure handling

def test_hook_exception_reports_error_and_keeps_state():
    code = "def on_tick(state, world, emit):\n    state['x'] = 1\n    raise ValueError('boom')\n"
    res = tick(code, {"orig": True})
    assert res.ok is False
    assert isinstance(res.error, str) and res.error
    # original state on failure
    assert res.state == {"orig": True}
    # and the calling process trivially survives (we are still here)


def test_code_that_fails_to_parse_reports_error():
    res = tick("def on_tick(state world emit:\n")
    assert res.ok is False
    assert res.error


# -------------------------------------------------------------- restrictions

def test_import_statement_fails():
    code = "def on_tick(state, world, emit):\n    import os\n    state['pwd'] = os.getcwd()\n"
    res = tick(code)
    assert res.ok is False
    assert res.error


def test_open_is_unavailable():
    code = "def on_tick(state, world, emit):\n    open('/etc/passwd')\n"
    res = tick(code)
    assert res.ok is False
    assert res.error


def test_eval_exec_getattr_unavailable():
    for snippet in ("eval('1+1')", "exec('x = 1')", "getattr(state, 'keys')"):
        code = "def on_tick(state, world, emit):\n    %s\n" % snippet
        res = tick(code)
        assert res.ok is False, snippet
        assert res.error, snippet


def test_math_random_json_preloaded():
    code = (
        "def on_tick(state, world, emit):\n"
        "    state['m'] = math.floor(2.7)\n"
        "    random.seed(1)\n"
        "    state['r'] = random.randint(1, 10)\n"
        "    state['j'] = json.dumps({'a': 1})\n"
    )
    res = tick(code)
    assert res.ok is True
    assert res.state["m"] == 2
    assert 1 <= res.state["r"] <= 10
    assert res.state["j"] == '{"a": 1}'


def test_common_builtins_and_classes_work():
    code = (
        "class Counter:\n"
        "    def __init__(self):\n"
        "        self.n = 0\n"
        "    def bump(self):\n"
        "        self.n += 1\n"
        "        return self.n\n"
        "def on_tick(state, world, emit):\n"
        "    c = Counter()\n"
        "    c.bump()\n"
        "    state['len'] = len([1, 2, 3])\n"
        "    state['range'] = list(range(3))\n"
        "    state['sorted'] = sorted([3, 1, 2])\n"
        "    state['sum'] = sum([1, 2, 3])\n"
        "    try:\n"
        "        int('not a number')\n"
        "    except ValueError:\n"
        "        state['caught'] = True\n"
        "    state['cls'] = c.bump()\n"
    )
    res = tick(code)
    assert res.ok is True
    assert res.state["len"] == 3
    assert res.state["range"] == [0, 1, 2]
    assert res.state["sorted"] == [1, 2, 3]
    assert res.state["sum"] == 6
    assert res.state["caught"] is True
    assert res.state["cls"] == 2


# ------------------------------------------------------------------- limits

def test_infinite_loop_is_killed():
    code = "def on_tick(state, world, emit):\n    while True:\n        pass\n"
    res = tick(code, cpu_seconds=1, wall_timeout=4.0)
    assert res.ok is False
    assert isinstance(res.error, str) and res.error
    # caller survives — execution continues


def test_emit_rejects_non_dict_payload():
    code = "def on_tick(state, world, emit):\n    emit('not a dict')\n"
    res = tick(code)
    assert res.ok is False
    assert res.error


def test_non_serializable_state_values_coerced_to_str():
    code = (
        "class Thing:\n"
        "    pass\n"
        "def on_tick(state, world, emit):\n"
        "    state['obj'] = Thing()\n"
    )
    res = tick(code)
    assert res.ok is True
    assert isinstance(res.state["obj"], str)
