"""An authenticated HTTP client around a daemon app with the fake provider."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from nestd.api.app import create_app
from nestd.context import AppContext
from nestd.local.service import LocalSetup
from nestd.providers.acp_process import AcpTransportFactory
from tests.acp_engine_support import FakeNpm
from tests.api_support import build_context, local_token
from tests.codex_support import FakeAppServer
from tests.fake_claude import FakeClaude
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
        claude: FakeClaude,
        codex: FakeAppServer,
        npm: FakeNpm,
        transport: httpx.AsyncBaseTransport,
    ) -> None:
        self.ctx = ctx
        self.http = http
        self.provider = provider
        self.runner = runner
        self.opener = opener
        self.probes = probes
        self.engine = engine
        self.restart = restart
        self.claude = claude
        self.codex = codex
        self.npm = npm
        # The app's own transport, for other clients of it, such as the `nest` command's.
        self.transport = transport


def wants_loops(request: pytest.FixtureRequest) -> bool:
    """Whether the test is marked to run the timer loops (`@pytest.mark.loops`)."""
    return "loops" in request.keywords


@asynccontextmanager
async def running_api(
    tmp_path: Path,
    clock: FakeClock,
    secrets: FakeSecretStore,
    push_transport: httpx.AsyncBaseTransport | None = None,
    codex_home: Path | None = None,
    local_setup: LocalSetup | None = None,
    loops: bool = False,
    acp: AcpTransportFactory | None = None,
) -> AsyncGenerator[Api]:
    """Without `loops`, the services that poll on a timer stay stopped (B111): their own
    tests drive them, and their real-time ticks would race the test.
    """
    provider = FakeProvider()
    runner = FakeRunner()
    opener = FakeOpener()
    probes = FakeProbeFactory()
    engine = FakeInfoFactory()
    claude = FakeClaude()
    codex = FakeAppServer()
    npm = FakeNpm()
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
        claude=claude,
        codex=codex,
        codex_home=codex_home,
        local_setup=local_setup,
        npm=npm,
        acp=acp,
    )
    restart = RecordingRestart()
    app = create_app(ctx, restart=restart, loops=loops)
    transport = httpx.ASGITransport(app=app)
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="https://mac.tailnet.ts.net") as http,
        ):
            http.headers["Authorization"] = f"Bearer {local_token(secrets)}"
            yield Api(
                ctx,
                http,
                provider,
                runner,
                opener,
                probes,
                engine,
                restart,
                claude,
                codex,
                npm,
                transport,
            )
    finally:
        await ctx.close()
