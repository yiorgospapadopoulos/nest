from fastapi import APIRouter

from nestd import __version__
from nestd.api.schemas import Health

router = APIRouter()


@router.get("/api/health")
async def health() -> Health:
    return Health(status="ok", version=__version__)
