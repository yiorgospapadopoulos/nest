"""The setup guide (B130): whether it shows, what it finishes with, and the checks it draws."""

import asyncio

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.doctor.checks import run_checks
from nestd.doctor.models import SetupChecks
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
