from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from harness import __version__
from harness.api.errors import install_error_handlers
from harness.api.hosts import HostCheckMiddleware
from harness.api.routes import (
    agents,
    approvals,
    attachments,
    claude_chats,
    clients,
    connectors,
    devices,
    engine,
    events,
    health,
    local_apps,
    notifications,
    pairing,
    pixie_teams,
    pixies,
    prs,
    push,
    repos,
    review,
    search,
    sessions,
    stuck,
    usage,
)
from harness.api.static import install_static
from harness.context import AppContext


def create_app(ctx: AppContext) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        await ctx.devices.ensure_local_device()
        await ctx.approvals.expire_stale()
        await ctx.sessions.recover()
        await ctx.tracking.stop_stale()
        if ctx.token_socket is not None:
            await ctx.token_socket.start()
        try:
            await ctx.modules.start_enabled(ctx.settings.modules.enabled, ctx)
            await ctx.notifications.start()
            await ctx.claude_chats.start()
            await ctx.usage_refresher.start()
            await ctx.prs.monitor.start()
            await ctx.search.start()
            await ctx.stuck.start()
            await ctx.engine.start()
            yield
        finally:
            # First, so nothing asks for the token from a daemon that is going away.
            if ctx.token_socket is not None:
                await ctx.token_socket.stop()
            await ctx.engine.stop()
            await ctx.stuck.stop()
            await ctx.search.stop()
            await ctx.prs.monitor.stop()
            await ctx.usage_refresher.stop()
            await ctx.claude_chats.stop()
            await ctx.sessions.shutdown()
            await ctx.notifications.stop()
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
    app.add_middleware(HostCheckMiddleware, allowed=lambda: ctx.settings.server.allowed_hosts)
    install_error_handlers(app)
    for module in (
        health,
        pairing,
        devices,
        events,
        repos,
        attachments,
        sessions,
        pixies,
        pixie_teams,
        claude_chats,
        search,
        review,
        prs,
        approvals,
        connectors,
        usage,
        stuck,
        engine,
        agents,
        clients,
        local_apps,
        push,
        notifications,
    ):
        app.include_router(module.router)
    # Last, so every /api route matches first.
    install_static(app, ctx.paths.web_dist)
    return app
