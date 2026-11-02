"""Quality gates (C17): each part's latest gate time from `make check`, and the whole
latest check."""

import asyncio

from nestd.gates.rules import ALL_PARTS
from nestd.perf.gate_times import GateTimes
from nestd.perf.models import Collected, Measured

_PART_NAMES = {"daemon": "Daemon", "web": "iPhone web app", "apple": "Mac app"}


class Gates:
    def __init__(self, times: GateTimes) -> None:
        self._times = times

    async def __call__(self) -> Collected:
        runs = await asyncio.to_thread(self._times.read)
        metrics: list[Measured] = []
        for part in ALL_PARTS:
            latest = next((run for run in reversed(runs) if part in run.parts), None)
            metrics.append(
                Measured(
                    id=part,
                    label=_PART_NAMES[part],
                    unit="ms",
                    better="lower",
                    value=None if latest is None else latest.parts[part],
                )
            )
        last = runs[-1] if runs else None
        metrics.append(
            Measured(
                id="whole",
                label="Whole check",
                unit="ms",
                better="lower",
                value=None if last is None else last.total_ms,
                sub=None if last is None else ", ".join(_PART_NAMES.get(p, p) for p in last.parts),
            )
        )
        note = None if runs else "No check recorded yet: run make check."
        return Collected(metrics=metrics, note=note)
