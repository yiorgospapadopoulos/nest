"""One collector per section of Settings > Performance (C5 to C17). Each is called with
nothing and returns that section's results; the Mac app measures its own section."""

from collections.abc import Awaitable, Callable

from nestd.perf.models import Collected

type Collector = Callable[[], Awaitable[Collected]]
