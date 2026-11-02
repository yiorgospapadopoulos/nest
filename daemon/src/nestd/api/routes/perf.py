from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field

from nestd.api.deps import Context, RequireDevice
from nestd.perf.models import PerfView

router = APIRouter(prefix="/api/perf", dependencies=[RequireDevice])


class StartRun(BaseModel):
    # Empty: every section the daemon measures.
    sections: Annotated[list[str], Field(max_length=50)] = Field(default_factory=list[str])


class ClientResult(BaseModel):
    section: str
    metrics: Annotated[dict[str, float | None], Field(max_length=50)]


@router.get("")
async def perf(ctx: Context) -> PerfView:
    """Settings > Performance (B115): each section's latest results against the run
    before, the four cards, What changed, and the run in progress if any."""
    return await ctx.perf.view()


@router.post("/runs")
async def start_run(ctx: Context, body: StartRun | None = None) -> PerfView:
    """Run these sections (none: all the daemon measures) in the background; `perf.run`
    says when it finishes. 409 while a run is running."""
    return await ctx.perf.start(body.sections if body is not None else [])


@router.post("/client")
async def client_result(body: ClientResult, ctx: Context) -> PerfView:
    """A section a client measures itself (the Mac app's), recorded as a finished run."""
    return await ctx.perf.record_client(body.section, body.metrics)


@router.post("/clear")
async def clear_runs(ctx: Context) -> PerfView:
    """Keep each section's two latest runs; delete the rest."""
    return await ctx.perf.clear()
