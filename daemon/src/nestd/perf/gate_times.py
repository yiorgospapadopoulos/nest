"""How long `make check` took on this Mac (C17): one JSON line per passing run in
`gate-times.jsonl` in Nest's data folder, written by `nestd gates record`."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

GATE_TIMES = "gate-times.jsonl"


class GateRun(BaseModel):
    at: datetime
    # Each part's lint, test and audit stages summed, in milliseconds.
    parts: dict[str, int]
    total_ms: int


@dataclass(frozen=True)
class GateTimes:
    path: Path

    @classmethod
    def in_folder(cls, data_dir: Path) -> "GateTimes":
        return cls(data_dir / GATE_TIMES)

    def record(self, run: GateRun) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(run.model_dump_json() + "\n")

    def read(self) -> list[GateRun]:
        """Oldest first; lines that are not a run are skipped."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        runs: list[GateRun] = []
        for line in lines:
            try:
                runs.append(GateRun.model_validate(json.loads(line)))
            except (ValueError, ValidationError):
                continue
        return runs


def stage_times(items: list[str]) -> dict[str, int]:
    """`part=ms` items, one per stage, summed per part in the order first named."""
    parts: dict[str, int] = {}
    for item in items:
        part, sep, ms = item.partition("=")
        if not sep or not part or not ms.isdigit():
            msg = f"expected part=milliseconds, got {item!r}"
            raise ValueError(msg)
        parts[part] = parts.get(part, 0) + int(ms)
    return parts
