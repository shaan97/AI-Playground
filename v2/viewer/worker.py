"""viewer.worker — runs one experiment and streams it to a run directory.

Launched by :class:`viewer.jobs.JobManager` as ``python -m viewer.worker
<run_dir>``. It reads the launch spec from ``run.json``, builds the world, and
steps it, appending the trajectory and agent transcripts to the directory as it
goes (via :class:`viewer.persistence.RunWriter`) so the control plane can tail it
live. Between steps it consults ``control.json`` for operator pause/resume/stop —
mirroring the substrate's "check between steps, never tear a step mid-flight"
rule; the world model itself stays pure.

Two world kinds:
    demo  — a model-free scripted world (examples/viewer_demo.py); needs nothing.
    gemma — real Ollama LLM agents (examples/gemma_world.py); needs Ollama.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent  # v2/
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from viewer.hub import ViewerHub  # noqa: E402
from viewer.persistence import RunWriter  # noqa: E402


def build_world(spec: dict):
    """Construct a GraphDynamicalSystem from a launch spec."""
    kind = spec.get("kind", "demo")
    if kind == "gemma":
        from examples.gemma_world import build, PROMPT_LEVELS
        system = spec.get("system")
        if not system:
            system = PROMPT_LEVELS.get(int(spec.get("level", 0) or 0), "")
        return build(
            spec.get("model", "gemma4"),
            spec.get("url", "http://127.0.0.1:11434"),
            system,
            objects=not spec.get("bare", False),
            n_agents=int(spec.get("agents", 1) or 1),
            continuous=bool(spec.get("continuous", True)),
        )
    if kind == "demo":
        import random
        from examples.viewer_demo import build as demo_build
        random.seed(spec.get("seed", 7))
        return demo_build()
    raise ValueError(f"unknown world kind {kind!r}")


def read_command(run_dir: Path) -> str | None:
    """The last operator command, if any (pause / resume / stop)."""
    try:
        return json.loads((run_dir / "control.json").read_text(encoding="utf-8")).get("command")
    except (OSError, ValueError):
        return None


def collect_traces(hub: ViewerHub, step: int) -> dict[str, list]:
    """This step's per-agent turn transcripts, captured by the hub."""
    out = {}
    for agent in hub.meta().get("agents", []):
        messages = hub.trace(step, agent).get("messages")
        if messages:
            out[agent] = messages
    return out


def run(run_dir: str | Path) -> int:
    run_dir = Path(run_dir)
    spec = json.loads((run_dir / "run.json").read_text(encoding="utf-8")).get("spec", {})
    steps = int(spec.get("steps") or 0)        # 0 => unlimited
    delay = float(spec.get("delay") or 0.0)

    writer = RunWriter(run_dir)
    try:
        gds = build_world(spec)
    except Exception as exc:
        writer.set_status("crashed", step=0, error=f"build failed: {exc!r}")
        raise

    hub = ViewerHub().instrument(gds)
    writer.genesis(gds)
    hub.publish(gds)  # genesis snapshot (step 0, no turns)

    state = "running"
    stopped = False
    done = 0
    try:
        while steps == 0 or done < steps:
            cmd = read_command(run_dir)
            if cmd == "stop":
                stopped = True
                break
            if cmd == "pause":
                if state != "paused":
                    writer.set_status("paused", step=gds.step_index)
                    state = "paused"
                time.sleep(max(delay, 0.25))
                continue
            if state != "running":
                writer.set_status("running", step=gds.step_index)
                state = "running"

            gds.step()
            hub.publish(gds)
            writer.record_step(gds, collect_traces(hub, gds.step_index))
            done += 1
            if delay:
                time.sleep(delay)
    except Exception as exc:
        writer.finish(gds, state="crashed", error=repr(exc))
        raise

    writer.finish(gds, state="stopped" if stopped else "done")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m viewer.worker <run_dir>", file=sys.stderr)
        return 2
    return run(argv[0])


if __name__ == "__main__":
    raise SystemExit(main())
