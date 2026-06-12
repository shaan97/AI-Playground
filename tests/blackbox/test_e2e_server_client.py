"""End-to-end: run_server.py + run_client.py as subprocesses
(docs/INTERFACES.md §CLI surfaces, PROTOCOL.md §Remote mode)."""
import json
import subprocess
import sys
import time

from conftest import REPO, free_port, http


def wait_for_server(url, data_dir, proc, timeout=30):
    """Wait until tokens.json exists and the server answers /world."""
    deadline = time.time() + timeout
    tokens = None
    while time.time() < deadline:
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=5)
            raise AssertionError("server exited early: %s\n%s" % (out, err))
        tokens_path = data_dir / "tokens.json"
        if tokens is None and tokens_path.exists():
            try:
                tokens = json.loads(tokens_path.read_text())
            except ValueError:
                tokens = None  # partially written; retry
        if tokens:
            try:
                status, _ = http("GET", url + "/world",
                                 token=tokens["admin"], timeout=3)
                if status == 200:
                    return tokens
            except OSError:
                pass
        time.sleep(0.2)
    raise AssertionError("server did not become ready in %ss" % timeout)


def run_client(args, timeout=90):
    return subprocess.run(
        [sys.executable, "run_client.py"] + args,
        cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
    )


def test_server_and_mock_client_end_to_end(tmp_path):
    data_dir = tmp_path / "srv"
    port = free_port()
    url = "http://127.0.0.1:%d" % port
    server = subprocess.Popen(
        [sys.executable, "run_server.py", "--names", "aria,bram",
         "--host", "127.0.0.1", "--port", str(port),
         "--tick-interval", "0", "--data-dir", str(data_dir)],
        cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        tokens = wait_for_server(url, data_dir, server)
        assert set(tokens["agents"]) == {"aria", "bram"}

        # client takes its genesis wake and exits after one wake
        p = run_client(["--server", url, "--agent", "aria",
                        "--token", tokens["agents"]["aria"],
                        "--mock", "--max-wakes", "1", "--wait", "5"])
        assert p.returncode == 0, p.stderr
        ws = data_dir / "agents" / "aria" / "workspace"
        assert (ws / "identity.md").exists()
        assert (ws / "memory.md").exists()
        mem_len = len((ws / "memory.md").read_text())

        # the wake was acked: a fresh client now sees nothing... so feed it
        # an operator event plus a step, then run one more wake
        status, body = http("POST", url + "/admin/inject", token=tokens["admin"],
                            body={"text": "operator: hello aria", "to": "aria"})
        assert status == 200 and body == {"ok": True}
        status, body = http("POST", url + "/admin/step",
                            token=tokens["admin"], body={})
        assert status == 200 and body["tick"] >= 1

        p = run_client(["--server", url, "--agent", "aria",
                        "--token", tokens["agents"]["aria"],
                        "--mock", "--max-wakes", "1", "--wait", "5"])
        assert p.returncode == 0, p.stderr
        # the mock's later wake appended to memory.md on the server disk
        assert len((ws / "memory.md").read_text()) > mem_len

        # world state on disk reflects the run (server persists as it goes
        # or on shutdown; check the world endpoint while it is live)
        status, body = http("GET", url + "/world", token=tokens["agents"]["bram"])
        assert status == 200
        assert body["tick"] >= 1
        assert body["agents"] == ["aria", "bram"]
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=15)

    # after a SIGTERM shutdown the world is persisted on disk
    meta = json.loads((data_dir / "meta.json").read_text())
    assert meta["agents"] == ["aria", "bram"]
    assert meta["tick"] >= 1
