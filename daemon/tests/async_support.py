import asyncio
from collections.abc import Awaitable, Callable


async def until(condition: Callable[[], bool | Awaitable[bool]], seconds: float = 5) -> None:
    """Wait until `condition` holds; database work runs in a thread, so poll briefly."""
    async with asyncio.timeout(seconds):
        while True:
            result = condition()
            if result if isinstance(result, bool) else await result:
                return
            await asyncio.sleep(0.005)
