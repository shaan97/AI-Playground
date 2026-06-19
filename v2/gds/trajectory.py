"""The trajectory: the sequence of configurations a run passes through.

Because the world *is* a time series of configurations, recording every step's
configuration makes the whole history inspectable and replayable. Reproducing a
run is **record-replay** — re-reading the log — which works regardless of whether
the kernels were deterministic (an LLM agent need not be).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .configuration import Configuration


@dataclass
class Trajectory:
    snapshots: list[Configuration] = field(default_factory=list)

    def record(self, config: Configuration) -> None:
        self.snapshots.append(config)

    def __len__(self) -> int:
        return len(self.snapshots)

    def __getitem__(self, i: int) -> Configuration:
        return self.snapshots[i]

    # ----------------------------------------------------------- (de)serialise

    def to_jsonl(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for config in self.snapshots:
                f.write(json.dumps(config.to_dict(), ensure_ascii=False) + "\n")

    @staticmethod
    def from_jsonl(path: str | Path) -> "Trajectory":
        snapshots = [
            Configuration.from_dict(json.loads(line))
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return Trajectory(snapshots)
