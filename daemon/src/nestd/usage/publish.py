"""Usage windows as events, one kind per engine family (B91)."""

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.base import UsageInfo
from nestd.usage.models import CLAUDE


async def publish_usage(bus: EventBus, info: UsageInfo) -> None:
    """Claude's windows as `usage.updated`, its payload as before B91 (the iPhone and the
    usage warnings read it); another engine's as `usage.provider_updated`, with its name
    and its windows by length, each labelled.
    """
    if info.provider == CLAUDE:
        payload = info.model_dump(mode="json", exclude={"provider", "windows"})
        await bus.publish(types.USAGE_UPDATED, payload)
    else:
        payload = info.model_dump(mode="json", exclude={"five_hour", "seven_day"})
        await bus.publish(types.USAGE_PROVIDER_UPDATED, payload)
