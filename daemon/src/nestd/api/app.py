from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nestd import __version__
from nestd.api.cors import DesktopCorsMiddleware
from nestd.api.errors import install_error_handlers
from nestd.api.hosts import HostCheckMiddleware
from nestd.api.routes import (
    accounts,
    agents,
    approvals,
    artifacts,
    attachments,
    claude_chats,
    claude_code,
    clients,
    composer,
    configuration,
    connectors,
    devices,
    engine,
    events,
    extensions,
    features,
    goals,
    health,
    issues,
    local_apps,
    local_models,
    local_proxy,
    notifications,
    pairing,
    perf,
    pixie_groups,
    pixie_reports,
    pixie_settings,
    pixie_teams,
    pixies,
    prs,
    push,
    repos,
    review,
    runs,
    search,
    service,
    session_pixies,
    sessions,
    setup,
    storage,
    stuck,
    updates,
    usage,
)
from nestd.api.static import install_static
from nestd.context import AppContext
from nestd.perf.build import ready_ms
from nestd.perf.timing import TimingMiddleware
from nestd.service.restart import Restarter


def create_app(ctx: AppContext, *, restart: Restarter, loops: bool = True) -> FastAPI:
    """`restart` ends the daemon process for `POST /api/service/restart`. Without `loops`,
    the services that poll on a timer are not started, so tests drive them directly.
    """

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        await ctx.devices.ensure_local_device()
        await ctx.approvals.expire_stale()
        await ctx.sessions.recover()
        await ctx.tracking.stop_stale()
        await ctx.pixie_calls.stop_stale()
        # After the sessions: a background call's caller hears it was interrupted (B112).
        await ctx.pixie_call_runs.recover()
        # Stored defaults that left choices to the engines become concrete (B94).
        await ctx.settle_defaults()
        if ctx.token_socket is not None:
            await ctx.token_socket.start()
        try:
            await ctx.modules.start_enabled(ctx.settings.modules.enabled, ctx)
            await ctx.notifications.start()
            if loops:
                await ctx.claude_chats.start()
                await ctx.branch_watch.start()
                await ctx.usage_refresher.start()
                await ctx.prs.monitor.start()
                await ctx.search.start()
                await ctx.stuck.start()
                await ctx.engine.start()
            await ctx.report_back.start()
            if loops:
                await ctx.habit_scheduler.start()
            await ctx.habit_triggers.start()
            if loops:
                await ctx.sessions.start()
                await ctx.archiver.start()
            await ctx.usage_warnings.start()
            if loops:
                await ctx.configuration_watcher.start()
                await ctx.updates.start()
            # Last, so the start's time covers everything before serving (B115).
            await ctx.perf.started(ready_ms())
            yield
        finally:
            # First, so nothing asks for the token from a daemon that is going away.
            if ctx.token_socket is not None:
                await ctx.token_socket.stop()
            await ctx.perf.stop()
            await ctx.updates.stop()
            await ctx.configuration_watcher.stop()
            await ctx.archiver.stop()
            await ctx.usage_warnings.stop()
            # Before the agents stop: the runs they cut off count as restarted (B42).
            await ctx.habit_triggers.stop()
            await ctx.habit_scheduler.stop()
            await ctx.report_back.stop()
            await ctx.engine.stop()
            await ctx.stuck.stop()
            await ctx.search.stop()
            await ctx.prs.monitor.stop()
            await ctx.usage_refresher.stop()
            await ctx.branch_watch.stop()
            await ctx.claude_chats.stop()
            await ctx.sessions.shutdown()
            await ctx.pixie_call_runs.shutdown()
            # After the agents, which may use the dev servers until they stop.
            await ctx.runs.shutdown()
            await ctx.pr_adopter.settled()
            await ctx.notifications.stop()
            await ctx.modules.stop_all()

    app = FastAPI(
        title="Nest",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.ctx = ctx
    app.state.restart = restart
    # Inside the host check, so a refused host never gets CORS headers.
    app.add_middleware(DesktopCorsMiddleware, allowed=lambda: ctx.settings.server.allowed_origins)
    app.add_middleware(HostCheckMiddleware, allowed=lambda: ctx.settings.server.allowed_hosts)
    # Outside the host check: a refused request has no route, so it is not timed.
    app.add_middleware(TimingMiddleware, timings=ctx.perf_timings)
    install_error_handlers(app)
    for module in (
        health,
        pairing,
        devices,
        events,
        repos,
        attachments,
        sessions,
        runs,
        goals,
        session_pixies,
        pixie_groups,
        composer,
        pixie_settings,
        pixies,
        pixie_teams,
        pixie_reports,
        artifacts,
        claude_chats,
        search,
        review,
        prs,
        issues,
        approvals,
        connectors,
        usage,
        storage,
        stuck,
        engine,
        agents,
        clients,
        local_apps,
        local_models,
        setup,
        push,
        notifications,
        service,
        updates,
        accounts,
        claude_code,
        extensions,
        configuration,
        features,
        perf,
    ):
        app.include_router(module.router)
    # The engines reach local models' servers through it (B106); not under device auth.
    app.include_router(local_proxy.router)
    local_proxy.configure(
        app,
        resolve=ctx.local.resolve,
        key=ctx.local.translator_key,
        transport=ctx.local.transport,
        machine=ctx.platform.machine_noun,
    )
    # Last, so every /api route matches first.
    install_static(app, ctx.paths.web_dist)
    # Settings > Performance loads what the apps load from this app, in-process (B115).
    ctx.perf_fetch.attach(app)
    return app
