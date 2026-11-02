"""The sections of Settings > Performance, in the order the page shows them (C1). Clients
render them as served: every title, label, unit and note comes from here or a collector."""

from dataclasses import dataclass

from nestd.perf.formatting import Better, Unit
from nestd.perf.models import Runner


@dataclass(frozen=True)
class MetricSpec:
    id: str
    label: str
    unit: Unit
    better: Better


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    advanced: bool
    # Whether running it spends usage on an engine.
    live: bool = False
    runner: Runner = "daemon"
    note: str | None = None
    # Fixed metrics of a section measured by a client, which sends only the values.
    metrics: tuple[MetricSpec, ...] = ()


SECTIONS: tuple[Section, ...] = (
    Section(
        "context",
        "Context cost",
        advanced=False,
        live=True,
        note="One small Claude turn in General, set up as a new chat. Nest's parts are "
        "estimated from their text.",
    ),
    Section("turns", "Turn speed and cache", advanced=False, note="Turns of the last 7 days."),
    Section(
        "load",
        "Load speed",
        advanced=False,
        note="Times on the daemon; parsing on the device is not included.",
    ),
    Section(
        "waiting",
        "Waiting on you",
        advanced=False,
        note="Answers of the last 30 days; notifications since the daemon started.",
    ),
    Section("activity", "Activity", advanced=False),
    Section("pixies", "Pixies", advanced=True, note="The last 30 days."),
    Section("subagents", "Subagents", advanced=True, note="The last 30 days."),
    Section("reliability", "Reliability", advanced=True, note="The last 30 days."),
    Section(
        "engines",
        "Engines",
        advanced=True,
        live=True,
        note="The same tiny task on each signed-in engine, on its cheapest model.",
    ),
    Section(
        "mac",
        "Mac app",
        advanced=True,
        runner="mac",
        note="Measured by the Mac app on the biggest chat.",
        metrics=(
            MetricSpec("layout_ms", "Lay out the biggest chat", "ms", "lower"),
            MetricSpec("scroll_ms", "Scroll it through", "ms", "lower"),
            MetricSpec("memory_before", "Memory before", "bytes", "lower"),
            MetricSpec("memory_after", "Memory after", "bytes", "lower"),
        ),
    ),
    Section("daemon", "Daemon", advanced=True, note="Routes since the daemon started."),
    Section("worktrees", "Worktrees", advanced=True, note="Worktree chats of the last 30 days."),
    Section("gates", "Quality gates", advanced=True, note="Recorded by make check on this Mac."),
)

BY_ID = {section.id: section for section in SECTIONS}
# What "Run all" runs: the Mac app measures its own section.
DAEMON_SECTIONS = tuple(s.id for s in SECTIONS if s.runner == "daemon")


# The four cards at the top, shown before their first measurement too.
@dataclass(frozen=True)
class Card:
    section: str
    metric: MetricSpec


CARDS: tuple[Card, ...] = (
    Card("context", MetricSpec("total", "New chat context", "tokens", "lower")),
    Card("turns", MetricSpec("cache_rate", "Cache hit rate", "percent", "higher")),
    Card("turns", MetricSpec("first_reply", "First reply", "ms", "lower")),
    Card("load", MetricSpec("biggest_chat", "Biggest chat opens", "ms", "lower")),
)
