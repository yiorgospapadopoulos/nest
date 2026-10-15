from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from starlette.requests import HTTPConnection

from nestd.api.deps import RequireDevice
from nestd.api.schemas import Restarting
from nestd.service.restart import Restarter

router = APIRouter(prefix="/api/service", dependencies=[RequireDevice])


def get_restart(conn: HTTPConnection) -> Restarter:
    restart: Restarter = conn.app.state.restart
    return restart


@router.post("/restart", status_code=status.HTTP_202_ACCEPTED)
async def restart_service(
    background: BackgroundTasks, restart: Annotated[Restarter, Depends(get_restart)]
) -> Restarting:
    """Restart the daemon: answers first, then shuts down cleanly and launchd starts it again."""
    background.add_task(restart)
    return Restarting(restarting=True)
