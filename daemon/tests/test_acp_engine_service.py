"""B107: how an ACP engine's process starts, on which account and with which key, and
when it is refused.
"""

import asyncio
import json
import logging
import shlex
import sys
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest

from nestd.engine import acp as acp_module
from nestd.engine.acp import AcpEngineService, key_item
from nestd.engine.acp_install import EngineInstall
from nestd.engine.store import EngineInfoStore
from nestd.providers.acp import AcpNotReadyError, AcpProbe
from nestd.providers.acp_engines import (
    ANTIGRAVITY,
    CURSOR,
    GEMINI,
    GEMINI_KEY_ENV,
    GEMINI_SYSTEM_SETTINGS_ENV,
    OPENCODE,
    AcpEngine,
)
from nestd.providers.acp_process import AcpLaunch, AcpTransportFactory
from nestd.providers.base import ModelOption, RunAccount
from nestd.storage.db import Database
from tests.acp_engine_support import FREE_MODELS, FakeNpm, no_engine_process, preinstall
from tests.fakes import FakeClock, FakeSecretStore

SHELL = {"PATH": "/usr/bin", GEMINI_KEY_ENV: "shell-key", "OPENCODE_PERMISSION": "{}"}


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = await Database.open(tmp_path / "nest.db")
    yield database
    await database.close()


class Rig:
    def __init__(self, tmp_path: Path, db: Database, clock: FakeClock) -> None:
        self.tmp_path = tmp_path
        self.db = db
        self.clock = clock
        self.secrets = FakeSecretStore()
        self.npm = FakeNpm()
        self.active = RunAccount("gemini-main")

    def service(self, engine: AcpEngine) -> AcpEngineService:
        async def env() -> Mapping[str, str]:
            return SHELL

        async def active() -> RunAccount:
            return self.active

        root = self.tmp_path / "engines"
        return AcpEngineService(
            engine,
            EngineInstall(engine, root, self.npm, env, self.tmp_path / "home"),
            EngineInfoStore(self.db, self.clock, f"{engine.id}_"),
            self.secrets,
            self.clock,
            env,
            active,
            no_engine_process,
        )


@pytest.fixture
def rig(tmp_path: Path, db: Database, clock: FakeClock) -> Rig:
    return Rig(tmp_path, db, clock)


def fake_probe(
    monkeypatch: pytest.MonkeyPatch, answer: AcpProbe, seen: list[AcpLaunch] | None = None
) -> None:
    async def probe(launch: AcpLaunch, cwd: Path, transport: AcpTransportFactory) -> AcpProbe:
        del cwd, transport
        if seen is not None:
            seen.append(launch)
        return answer

    monkeypatch.setattr(acp_module, "probe", probe)


async def test_gemini_runs_with_the_accounts_keychain_key_and_nests_settings(rig: Rig) -> None:
    program = preinstall(rig.tmp_path / "engines", GEMINI)
    service = rig.service(GEMINI)
    rig.secrets.set(key_item("gemini-main"), "keychain-key")
    home = rig.tmp_path / "profiles" / "gemini" / "abc"
    rig.secrets.set(key_item("abc"), "work-key")

    first = await service.launch(RunAccount("gemini-main"))
    added = await service.launch(RunAccount("abc", {"GEMINI_CLI_HOME": str(home)}))

    assert first.args == (str(program), "--acp", "--approval-mode", "default")
    assert first.env[GEMINI_KEY_ENV] == "keychain-key"
    assert (added.env[GEMINI_KEY_ENV], added.env["GEMINI_CLI_HOME"]) == ("work-key", str(home))
    settings = await asyncio.to_thread(
        Path(first.env[GEMINI_SYSTEM_SETTINGS_ENV]).read_text, encoding="utf-8"
    )
    # The key is only in the process environment, never in a file Nest writes.
    assert settings == '{"security":{"disableAlwaysAllow":true}}'


async def test_only_the_first_gemini_account_falls_back_to_the_shells_key(rig: Rig) -> None:
    preinstall(rig.tmp_path / "engines", GEMINI)
    service = rig.service(GEMINI)

    first = await service.launch(None)
    with pytest.raises(AcpNotReadyError, match="API key"):
        await service.launch(RunAccount("abc", {"GEMINI_CLI_HOME": "/x"}))
    rig.active = RunAccount("abc")
    with pytest.raises(AcpNotReadyError):
        await service.require_ready()

    assert first.env[GEMINI_KEY_ENV] == "shell-key"


async def test_nests_engine_settings_win_over_the_users_shell(rig: Rig) -> None:
    preinstall(rig.tmp_path / "engines", OPENCODE)
    home = rig.tmp_path / "profiles" / "opencode" / "abc"

    launch = await rig.service(OPENCODE).launch(
        RunAccount("abc", {"XDG_DATA_HOME": str(home / "data")})
    )

    assert launch.env["OPENCODE_PERMISSION"] == OPENCODE.env["OPENCODE_PERMISSION"]
    assert launch.env["XDG_DATA_HOME"] == str(home / "data")
    assert launch.env["PATH"] == "/usr/bin"


async def test_a_missing_engine_is_refused_and_starts_installing(rig: Rig) -> None:
    service = rig.service(OPENCODE)

    with pytest.raises(AcpNotReadyError, match="being installed"):
        await service.require_ready()
    # Waits for the install that started in the background.
    await service.install.install()

    assert (await service.install.current()).state == "ready"
    assert rig.npm.installs() == ["opencode-ai@1.19.5"]


async def test_a_terminal_engine_signed_out_is_refused_with_its_login_command(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = rig.tmp_path / "home" / ".local" / "bin" / "agent"
    program.parent.mkdir(parents=True)
    program.write_text("#!/bin/sh\n", encoding="utf-8")
    rig.active = RunAccount("cursor-main")
    fake_probe(monkeypatch, AcpProbe(models=[], signed_in=False, agent_version=None, mcp_http=True))
    service = rig.service(CURSOR)

    with pytest.raises(AcpNotReadyError, match="agent login"):
        await service.require_ready()
    status = await service.status()

    assert status.signed_in is False
    assert status.login_command == f"{program} login"


def opencode_login(data: Path, content: str) -> None:
    """OpenCode's own login file under an XDG_DATA_HOME, as `opencode auth login` leaves it."""
    path = data / "opencode" / "auth.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.parametrize("content", [None, "{}", "not json"])
async def test_opencode_is_signed_out_without_a_login_and_refuses_a_chat(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, content: str | None
) -> None:
    program = preinstall(rig.tmp_path / "engines", OPENCODE)
    data = rig.tmp_path / "profiles" / "opencode" / "abc" / "data"
    if content is not None:
        opencode_login(data, content)
    rig.active = RunAccount("abc", {"XDG_DATA_HOME": str(data)})
    # It answers ACP signed out, on its free models: the probe cannot tell.
    fake_probe(monkeypatch, AcpProbe(models=[], signed_in=True, agent_version=None, mcp_http=True))
    service = rig.service(OPENCODE)

    with pytest.raises(AcpNotReadyError, match="opencode auth login"):
        await service.require_ready()
    status = await service.status()
    account = await service.account_status(rig.active)

    assert (status.signed_in, account.signed_in) == (False, False)
    # Signs in the account's own folder, with the engine Nest runs.
    assert status.login_command == f"XDG_DATA_HOME={data} {program} auth login"


async def test_opencode_is_signed_in_once_its_login_holds_a_provider(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    preinstall(rig.tmp_path / "engines", OPENCODE)
    # The first account has no folder of its own: the user's `~/.local/share`.
    opencode_login(rig.tmp_path / "home" / ".local" / "share", '{"anthropic": {"type": "api"}}')
    rig.active = RunAccount("opencode-main")
    fake_probe(monkeypatch, AcpProbe(models=[], signed_in=False, agent_version=None, mcp_http=True))
    service = rig.service(OPENCODE)

    await service.require_ready()
    status = await service.status()
    other = await service.account_status(
        RunAccount("abc", {"XDG_DATA_HOME": str(rig.tmp_path / "abc")})
    )

    assert status.signed_in is True
    assert other.signed_in is False


async def test_the_model_list_comes_from_a_probe_and_is_kept(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    preinstall(rig.tmp_path / "engines", OPENCODE)
    opencode_login(rig.tmp_path / "home" / ".local" / "share", '{"opencode": {"type": "api"}}')
    rig.active = RunAccount("opencode-main")
    seen: list[AcpLaunch] = []
    answer = AcpProbe(models=FREE_MODELS, signed_in=True, agent_version="1.19.5", mcp_http=True)
    fake_probe(monkeypatch, answer, seen)
    service = rig.service(OPENCODE)

    status = await service.status()
    listed = await service.models()
    again = await service.status()

    assert (status.state, status.signed_in, status.version) == ("ready", True, "1.19.5")
    assert [model.value for model in listed.models] == ["opencode/big-pickle"]
    assert await service.default_model() == "opencode/big-pickle"
    assert again is status
    assert len(seen) == 1


async def test_opencode_marks_the_models_of_the_users_local_servers(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    preinstall(rig.tmp_path / "engines", OPENCODE)
    opencode_login(rig.tmp_path / "home" / ".local" / "share", '{"opencode": {"type": "api"}}')
    rig.active = RunAccount("opencode-main")
    config = rig.tmp_path / "home" / ".config" / "opencode"
    config.mkdir(parents=True)
    (config / "opencode.jsonc").write_text(
        """{
          // A tunnel to the user's own box.
          "provider": {
            "mine": {"options": {"baseURL": "http://127.0.0.1:18080/v1"}},
            "hosted": {"options": {"baseURL": "https://api.example.com/v1"}},
          },
        }"""
    )
    values = ("lmstudio/ornith", "mine//opt/model.gguf", "hosted/big", "opencode/big-pickle")
    answer = AcpProbe(
        models=[ModelOption(value=value, display_name=value, description="") for value in values],
        signed_in=True,
        agent_version="1.19.5",
        mcp_http=True,
    )
    fake_probe(monkeypatch, answer, [])

    listed = await rig.service(OPENCODE).models()

    assert [model.value for model in listed.models if model.local] == [
        "lmstudio/ornith",
        "mine//opt/model.gguf",
    ]


async def test_a_failed_probe_logs_no_key(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    preinstall(rig.tmp_path / "engines", GEMINI)
    rig.secrets.set(key_item("gemini-main"), "secret-key-123")

    async def probe(launch: AcpLaunch, cwd: Path, transport: AcpTransportFactory) -> AcpProbe:
        del cwd, transport
        msg = f"engine said {launch.env[GEMINI_KEY_ENV]}"
        raise RuntimeError(msg)

    monkeypatch.setattr(acp_module, "probe", probe)
    with caplog.at_level(logging.DEBUG):
        status = await rig.service(GEMINI).status()

    assert status.signed_in is True
    assert "secret-key-123" not in caplog.text


async def test_antigravity_signs_in_through_nest_and_counts_only_its_login_file(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B153: its probe could open the browser on a login it cannot refresh, so Nest reads
    its login file instead, and the probe can never open one."""
    program = preinstall(rig.tmp_path / "engines", ANTIGRAVITY)
    rig.active = RunAccount("antigravity-main")
    seen: list[AcpLaunch] = []
    fake_probe(monkeypatch, AcpProbe(FREE_MODELS, True, "1.4.5", True), seen)
    service = rig.service(ANTIGRAVITY)

    with pytest.raises(AcpNotReadyError, match="Settings > Accounts"):
        await service.require_ready()
    signed_out = await service.status()
    token = rig.tmp_path / "home" / ".gemini" / "antigravity-acp" / "acp_token.json"
    token.parent.mkdir(parents=True)
    token.write_text('{"refresh_token": "x"}', encoding="utf-8")
    service.forget()
    signed_in = await service.status()
    launch = await service.launch(rig.active)

    assert signed_out.signed_in is False
    assert signed_out.login_command == shlex.join(
        [sys.executable, "-m", "nestd", "engines", "sign-in", "antigravity", str(program)]
    )
    assert signed_in.signed_in is True
    [probed] = seen
    assert probed.env["BROWSER"] == "true"
    assert "BROWSER" not in launch.env
    assert launch.env["AGY_ACP_FORCE_FILE_STORAGE"] == "1"


async def test_cursor_runs_on_a_copy_of_the_users_settings_that_asks(rig: Rig) -> None:
    program = rig.tmp_path / "home" / ".local" / "bin" / "agent"
    program.parent.mkdir(parents=True)
    program.write_text("#!/bin/sh\n", encoding="utf-8")
    user = rig.tmp_path / "home" / ".cursor" / "cli-config.json"
    user.parent.mkdir(parents=True)
    user.write_text('{"approvalMode": "unrestricted", "editor": {"vimMode": true}}')
    service = rig.service(CURSOR)

    launch = await service.launch(RunAccount("cursor-main"))

    folder = Path(launch.env["CURSOR_CONFIG_DIR"])
    assert folder == rig.tmp_path / "engines" / "cursor" / "config"
    written = json.loads((folder / "cli-config.json").read_text())
    assert written["approvalMode"] == "allowlist"
    assert written["editor"] == {"vimMode": True}
    assert launch.args == (str(program), "--disable-project-configs", "acp")
    assert json.loads(user.read_text())["approvalMode"] == "unrestricted"
