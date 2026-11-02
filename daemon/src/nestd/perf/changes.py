"""Each metric against the run before (C4), and the sentences of What changed (C18)."""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from nestd.perf.formatting import Unit, change, relative, signed, value_text
from nestd.perf.models import (
    ChangeView,
    Collected,
    Measured,
    MetricView,
    PartView,
    PerfRun,
    WhatChanged,
)

# A change worth a sentence: at least this share of the previous value...
SHARE_FLOOR = 0.10
# ...and at least this much in the metric's unit (a percent metric in points).
ABSOLUTE_FLOOR: dict[Unit, float] = {
    "tokens": 500,
    "ms": 100,
    "bytes": 50_000,
    "percent": 2,
    "count": 1,
}


@dataclass(frozen=True)
class Measurement:
    """A section's newest result and the one before it, with the runs they came from."""

    latest: Collected
    latest_run: PerfRun
    previous: Collected | None
    previous_run: PerfRun | None


def metric_view(metric: Measured, previous: Measured | None) -> MetricView:
    before = None if previous is None else previous.value
    shown_change = None
    if metric.value is not None and before is not None:
        text, direction, tone = change(metric.value, before, metric.unit, metric.better)
        # Below the unit's floor a move is noise (14 ms to 7 ms): shown, but not as better or worse.
        if abs(metric.value - before) < ABSOLUTE_FLOOR[metric.unit]:
            tone = "same"
        shown_change = ChangeView(text=text, direction=direction, tone=tone)
    return MetricView(
        id=metric.id,
        label=metric.label,
        sub=metric.sub,
        value=metric.value,
        unit=metric.unit,
        text=value_text(metric.value, metric.unit),
        previous=before,
        previous_text=None if before is None else value_text(before, metric.unit),
        change=shown_change,
        parts=None
        if metric.parts is None
        else [
            PartView(label=p.label, value=p.value, text=value_text(p.value, metric.unit))
            for p in metric.parts
        ],
        chat_id=metric.chat_id,
    )


def by_id(result: Collected | None) -> dict[str, Measured]:
    return {} if result is None else {m.id: m for m in result.metrics}


def what_changed(measurements: Sequence[tuple[str, Measurement]]) -> list[WhatChanged]:
    """Every metric that moved enough, worst first, with the cause when Nest can tell.
    Metrics that are neither better lower nor higher (activity) are left out."""
    found: list[tuple[int, float, WhatChanged]] = []
    for title, measurement in measurements:
        if measurement.previous is None or measurement.previous_run is None:
            continue
        before = by_id(measurement.previous)
        causes = _causes(measurement)
        for metric in measurement.latest.metrics:
            old = before.get(metric.id)
            if metric.better == "none" or metric.value is None or old is None:
                continue
            if old.value is None or not _notable(metric.value, old.value, metric.unit):
                continue
            _, _, tone = change(metric.value, old.value, metric.unit, metric.better)
            text = f"{title}, {metric.label.lower()} {signed(metric.value, old.value, metric.unit)}"
            if causes:
                text += f" ({'; '.join(causes)})"
            share = relative(metric.value, old.value)
            weight = abs(share) if share is not None else float("inf")
            found.append((0 if tone == "worse" else 1, -weight, WhatChanged(text=text, tone=tone)))
    found.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in found]


def _notable(value: float, previous: float, unit: Unit) -> bool:
    if abs(value - previous) < ABSOLUTE_FLOOR[unit]:
        return False
    share = relative(value, previous)
    return share is None or abs(share) >= SHARE_FLOOR


def _causes(measurement: Measurement) -> list[str]:
    latest, previous = measurement.latest_run, measurement.previous_run
    causes: list[str] = []
    if previous is None:
        return causes
    if latest.version != previous.version:
        causes.append(f"Nest {previous.version} to {latest.version}")
    elif latest.git_commit != previous.git_commit and latest.git_commit is not None:
        causes.append(f"Nest changed to {latest.git_commit}")
    old = measurement.previous.facts if measurement.previous is not None else {}
    causes += _setup_causes(old, measurement.latest.facts)
    return causes


def _setup_causes(old: dict[str, JsonValue], new: dict[str, JsonValue]) -> list[str]:
    """What the context run's facts say changed in the user's setup."""
    causes: list[str] = []
    before, after = _names(old.get("mcp_servers")), _names(new.get("mcp_servers"))
    if before is not None and after is not None:
        causes += [f"new MCP server {name}" for name in sorted(after - before)]
        causes += [f"MCP server {name} removed" for name in sorted(before - after)]
    skills_before, skills_after = old.get("skills"), new.get("skills")
    if (
        isinstance(skills_before, int)
        and isinstance(skills_after, int)
        and skills_after > skills_before
    ):
        causes.append(f"{skills_after - skills_before} more skills")
    for key, name in (
        ("user_claude_md", "your CLAUDE.md"),
        ("general_claude_md", "General's CLAUDE.md"),
    ):
        size_before, size_after = old.get(key), new.get(key)
        if (
            isinstance(size_before, int)
            and isinstance(size_after, int)
            and size_after > size_before
        ):
            causes.append(f"{name} grew by {value_text(size_after - size_before, 'bytes')}")
    return causes


def _names(raw: JsonValue | None) -> set[str] | None:
    if not isinstance(raw, list):
        return None
    return {name for name in raw if isinstance(name, str)}
