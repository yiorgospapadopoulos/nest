"""What a run measures, how it is stored, and what the API serves (B115)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from nestd.perf.formatting import Better, Direction, Tone, Unit

type RunState = Literal["running", "done", "failed"]
type Runner = Literal["daemon", "mac"]


class Part(BaseModel):
    label: str
    value: float


class Measured(BaseModel):
    """One measured metric as a run stores it; the label is kept with it because some
    sections name their metrics from what they found, such as a route or an engine."""

    id: str
    label: str
    unit: Unit
    better: Better
    value: float | None
    sub: str | None = None
    parts: list[Part] | None = None
    # The chat it measured, for the biggest chat: the Mac app opens that one to measure.
    chat_id: str | None = None


class Point(BaseModel):
    day: date
    value: float


class Series(BaseModel):
    label: str
    points: list[Point]


class Collected(BaseModel):
    """One section's results in one run. `facts` are what What changed reads to name a
    cause, such as the MCP servers that were loaded."""

    metrics: list[Measured] = Field(default_factory=list[Measured])
    series: Series | None = None
    note: str | None = None
    facts: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    error: str | None = None


class PerfRun(BaseModel):
    id: str
    sections: list[str]
    started_at: datetime
    finished_at: datetime | None
    state: RunState
    error: str | None
    version: str
    git_commit: str | None
    machine: str
    results: dict[str, Collected]


class ChangeView(BaseModel):
    text: str
    direction: Direction
    tone: Tone


class PartView(BaseModel):
    label: str
    value: float
    text: str


class MetricView(BaseModel):
    id: str
    label: str
    sub: str | None
    value: float | None
    unit: Unit
    text: str
    previous: float | None
    previous_text: str | None
    change: ChangeView | None
    parts: list[PartView] | None
    chat_id: str | None = None


class SectionView(BaseModel):
    id: str
    title: str
    advanced: bool
    runner: Runner
    live: bool
    ran_at: datetime | None
    error: str | None
    note: str | None
    metrics: list[MetricView]
    series: Series | None


class WhatChanged(BaseModel):
    text: str
    tone: Tone


class RunningView(BaseModel):
    id: str
    sections: list[str]
    started_at: datetime


class LastRun(BaseModel):
    finished_at: datetime
    duration_ms: int


class PerfView(BaseModel):
    running: RunningView | None
    last_run: LastRun | None
    cards: list[MetricView]
    sections: list[SectionView]
    changes: list[WhatChanged]
    runs: int
