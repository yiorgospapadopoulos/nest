"""An authenticated HTTP client around a daemon app with the fake provider."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from nestd.api.app import create_app
from nestd.context import AppContext
from tests.api_support import build_context, local_token
from tests.fake_engine import FakeInfoFactory
from tests.fake_opener import FakeOpener
from tests.fake_probe import FakeProbeFactory
from tests.fake_provider import FakeProvider
from tests.fake_runner import FakeRunner
from tests.fakes import FakeClock, FakeSecretStore, RecordingRestart


class Api:
    def __init__(
        self,
        ctx: AppContext,
        http: httpx.AsyncClient,
        provider: FakeProvider,
        runner: FakeRunner,
        opener: FakeOpener,
        probes: FakeProbeFactory,
        engine: FakeInfoFactory,
        restart: RecordingRestart,
    ) -> None:
        self.ctx = ctx
        self.http = http
        self.provider = provider
        self.runner = runner
        self.opener = opener
        self.probes = probes
        self.engine = engine
        self.restart = restart


@asynccontextmanager
async def running_api(
    tmp_path: Path,
    clock: FakeClock,
    secrets: FakeSecretStore,
    push_transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncGenerator[Api]:
    provider = FakeProvider()
    runner = FakeRunner()
    opener = FakeOpener()
    probes = FakeProbeFactory()
    engine = FakeInfoFactory()
    ctx = await build_context(
        tmp_path,
        clock,
        secrets,
        provider=provider,
        runner=runner,
        opener=opener,
        push_transport=push_transport,
        probe_factory=probes,
        engine_factory=engine,
    )
    restart = RecordingRestart()
    app = create_app(ctx, restart=restart)
    transport = httpx.ASGITransport(app=app)
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="https://mac.tailnet.ts.net") as http,
        ):
            http.headers["Authorization"] = f"Bearer {local_token(secrets)}"
            yield Api(ctx, http, provider, runner, opener, probes, engine, restart)
    finally:
        await ctx.close()
