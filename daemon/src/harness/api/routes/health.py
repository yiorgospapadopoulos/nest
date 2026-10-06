from fastapi import APIRouter

from harness import __version__
from harness.api.schemas import Health

router = APIRouter()


@router.get("/api/health")
async def health() -> Health:
    return Health(status="ok", version=__version__)
