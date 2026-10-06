from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from harness import __version__
from harness.api.errors import install_error_handlers
from harness.api.routes import (
    approvals,
    attachments,
    connectors,
    devices,
    events,
    health,
    local_apps,
    pairing,
    repos,
    review,
    sessions,
    usage,
)
from harness.context import AppContext
from harness.events import types


def create_app(ctx: AppContext) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        await ctx.devices.ensure_local_device()
        await ctx.approvals.expire_stale()
        await ctx.sessions.recover()
        try:
            await ctx.modules.start_enabled(ctx.settings.modules.enabled, ctx)
            await ctx.bus.publish(types.DAEMON_STARTED, {"version": __version__})
            yield
        finally:
            await ctx.sessions.shutdown()
            await ctx.modules.stop_all()

    app = FastAPI(
        title="harness",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.ctx = ctx
    install_error_handlers(app)
    for module in (
        health,
        pairing,
        devices,
        events,
        repos,
        attachments,
        sessions,
        review,
        approvals,
        connectors,
        usage,
        local_apps,
    ):
        app.include_router(module.router)
    return app
