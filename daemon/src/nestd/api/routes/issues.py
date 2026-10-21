from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.config.models import IssueShow
from nestd.issues.models import IssueList

router = APIRouter(prefix="/api", dependencies=[RequireDevice])


@router.get("/repos/{name}/issues")
async def repo_issues(
    name: str, ctx: Context, refresh: bool = False, show: IssueShow | None = None
) -> IssueList:
    """The project's open GitHub issues: all of them, or `mine` (assigned to the user);
    without `show`, as the project's `[issues] show` says. Newest updated first, read with
    the daemon's gh login and kept a minute; `available` is false without a GitHub remote.
    502 when GitHub cannot be read.
    """
    return await ctx.issues.list_issues(name, refresh, show)
