import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

from nestd.events.bus import EventBus, SubscriptionOverflowError

type Condition = Callable[[], bool | Awaitable[bool]]

# How often a condition is checked again when nothing is published: for changes that
# publish no event, and after a follower fell behind the bus.
_RECHECK = 0.25


async def until(condition: Condition, seconds: float = 5) -> None:
    """Wait until `condition` holds; database work runs in a thread, so poll briefly."""
    async with asyncio.timeout(seconds):
        while True:
            if await _holds(condition):
                return
            await asyncio.sleep(0.005)


async def until_published(bus: EventBus, condition: Condition, seconds: float = 30) -> None:
    """Wait until `condition` holds, checking it again whenever `bus` publishes an event
    (B111). `seconds` only guards against a hang.
    """
    published = asyncio.Event()

    async def follow(after: int) -> None:
        async for _event in bus.subscribe(after):
            published.set()

    # Events stored from here on wake the check, even those published before the follower
    # has subscribed.
    follower = asyncio.create_task(follow(await bus.last_id()))
    try:
        async with asyncio.timeout(seconds):
            while True:
                published.clear()
                if await _holds(condition):
                    return
                with suppress(TimeoutError):
                    await asyncio.wait_for(published.wait(), _RECHECK)
    finally:
        follower.cancel()
        with suppress(asyncio.CancelledError, SubscriptionOverflowError):
            await follower


async def _holds(condition: Condition) -> bool:
    result = condition()
    return result if isinstance(result, bool) else await result
