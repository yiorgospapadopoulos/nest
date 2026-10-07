from typing import Annotated

from fastapi import APIRouter, Query

from harness.api.deps import Context, RequireDevice
from harness.search.models import SearchResults

router = APIRouter(prefix="/api/search", dependencies=[RequireDevice])


@router.get("")
async def search(
    ctx: Context,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    repo: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchResults:
    """Chats whose titles or messages match `q`: words, "quoted phrases" and prefix* terms.

    Best match first, then newest. FTS syntax in `q` is searched as plain text.
    """
    return await ctx.search.search(q, repo, limit)
