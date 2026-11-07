"""The setup guide (B130): whether it shows, what it finishes with, and the checks it draws."""

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from nestd.api.deps import Context, RequireDevice
from nestd.doctor.checks import run_checks, share_on_tailnet
from nestd.doctor.models import Check, SetupChecks
from nestd.doctor.report import Report, write_report
from nestd.local.models import SetupState

router = APIRouter(prefix="/api/setup", dependencies=[RequireDevice])


@router.get("")
async def setup_state(ctx: Context) -> SetupState:
    return await ctx.local.setup()


@router.post("/local-only")
async def use_local_only(ctx: Context) -> SetupState:
    """Use local models only: no sign in is asked for, and the first run is over."""
    return await ctx.local.use_local_only()


@router.post("/done")
async def setup_done(ctx: Context) -> SetupState:
    return await ctx.local.finish_setup()


@router.get("/checks")
async def setup_checks(ctx: Context) -> SetupChecks:
    return SetupChecks(checks=await asyncio.to_thread(run_checks, ctx.doctor_machine()))


class ReportAsk(BaseModel):
    """The app's own answers, for the checks only it can make."""

    checks: list[Check] = []


@router.post("/report")
async def setup_report(ctx: Context, body: ReportAsk | None = None) -> Report:
    """Writes the file and returns its text to show; nothing is sent anywhere."""
    answers = [] if body is None else body.checks
    return await asyncio.to_thread(write_report, ctx.doctor_machine(), ctx.clock.now(), answers)


@router.post("/tailscale/share")
async def share_on_tailscale(ctx: Context) -> Check:
    """Runs `tailscale serve` for the user; the check again, or the link to turn HTTPS on."""
    return await asyncio.to_thread(share_on_tailnet, ctx.doctor_machine())
