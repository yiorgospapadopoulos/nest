"""Checking, preparing, relaunching and cleaning up. Network, uv and the check are fakes."""

import asyncio
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.events.models import Event
from nestd.paths import AppPaths
from nestd.providers.acp_engines import GEMINI, OPENCODE, in_environment
from nestd.providers.shell_env import no_shell_env
from nestd.storage.db import Database
from nestd.updates.boot import TrialWatch
from nestd.updates.build import PrepareError, UpdaterUnavailableError, run_selfcheck
from nestd.updates.engines import npm_engines
from nestd.updates.manifest import read_manifest
from nestd.updates.selfcheck import scratch_env
from nestd.updates.service import UpdateService, UpdateSetup
from nestd.updates.state import BASE, StateFile, UpdateState, rolled_back
from nestd.updates.versions import is_newer
from tests.acp_engine_support import FakeNpm
from tests.fakes import FakeClock
from tests.updates_support import (
    FINGERPRINT,
    NOW,
    SAME,
    FakeSelfcheck,
    FakeUv,
    make_environment,
    registry,
)

NEW_SDK = {**SAME, "claude-agent-sdk": "0.3.0"}


class RecordingBus(EventBus):
    def __init__(self, db: Database, clock: FakeClock) -> None:
        super().__init__(db, clock)
        self.sent: list[str] = []

    async def publish_ephemeral(
        self, event_type: str, payload: Mapping[str, JsonValue], session_id: str | None = None
    ) -> Event:
        assert event_type == types.UPDATES_CHANGED
        self.sent.append(str(payload["state"]))
        return await super().publish_ephemeral(event_type, payload, session_id)


class Rig:
    def __init__(self, tmp_path: Path, bus: RecordingBus) -> None:
        self.root = tmp_path / "environments"
        self.engines = tmp_path / "engines"
        for engine in npm_engines():
            (self.engines / engine.id).mkdir(parents=True)
        self.files = StateFile(self.root)
        self.bus = bus
        self.uv = FakeUv()
        self.npm = FakeNpm()
        self.selfcheck = FakeSelfcheck()
        self.prefix = tmp_path / "base"
        self.answers: list[bool] = []
        self.latest: httpx.MockTransport = registry(SAME)
        self.files.save(UpdateState(base_python="/base/bin/python", base_fingerprint=FINGERPRINT))

    def state(self, **fields: object) -> None:
        self.files.save(
            self.files.load().model_copy(update=fields),
        )

    def service(self, engines_wait: bool = False) -> UpdateService:
        async def healthy(_port: int) -> bool:
            return self.answers.pop(0) if self.answers else True

        async def wait() -> bool:
            return engines_wait

        return UpdateService(
            paths=AppPaths(config_dir=self.root.parent / "config", data_dir=self.root.parent),
            platform="macos",
            bus=self.bus,
            shell_env=no_shell_env,
            busy_chats=lambda: 0,
            port=lambda: 41010,
            setup=UpdateSetup(
                transport=self.latest,
                uv=self.uv,
                npm=self.npm,
                selfcheck=self.selfcheck,
                healthy=healthy,
                versions=lambda: NOW,
                prefix=self.prefix,
            ),
            engines_wait=wait,
        )

    async def check(self, service: UpdateService | None = None) -> UpdateService:
        """A whole check, waited for."""
        running = service or self.service()
        await running.check()
        await running.stop_when_done()
        return running

    def folders(self) -> list[str]:
        return sorted(entry.name for entry in self.root.iterdir() if entry.is_dir())


@pytest.fixture
def rig(tmp_path: Path, db: Database, clock: FakeClock) -> Rig:
    return Rig(tmp_path, RecordingBus(db, clock))


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("1.2.1", "1.2.0", True),
        ("1.10.0", "1.9.9", True),
        ("2", "1.9", True),
        ("1.2.0", "1.2.0", False),
        ("1.2", "1.2.0", False),
        ("1.1.9", "1.2.0", False),
        ("1.3.0rc1", "1.2.0", False),
        ("1.3.0-preview.1", "1.2.0", False),
        ("1.3.0.dev0", "1.2.0", False),
        ("1.3.0", "1.3.0b1", False),
        ("", "1.2.0", False),
    ],
)
def test_only_a_strictly_newer_stable_version_counts(
    candidate: str, current: str, newer: bool
) -> None:
    assert is_newer(candidate, current) is newer


async def test_nothing_newer_prepares_nothing(rig: Rig) -> None:
    rig.latest = registry({**SAME, "claude-agent-sdk": "0.3.0rc1", "opencode-ai": "0.9.0"})

    service = await rig.check()

    assert rig.uv.calls == []
    assert (await service.status()).state == "none"


async def test_a_pulled_release_does_not_count(rig: Rig) -> None:
    rig.latest = registry(NEW_SDK, yanked=["claude-agent-sdk"])

    await rig.check()

    assert rig.uv.calls == []


async def test_a_registry_that_fails_shows_nothing(rig: Rig) -> None:
    rig.latest = registry({"claude-agent-sdk": "0.3.0"})

    service = await rig.check()

    assert rig.uv.calls == []
    assert (await service.status()).state == "none"


async def test_a_new_version_is_prepared_checked_and_offered(rig: Rig) -> None:
    rig.latest = registry({**NEW_SDK, "opencode-ai": "1.1.0"})

    service = await rig.check()

    status = await service.status()
    assert status.state == "ready"
    # What people see: Claude Code's version, from the check, not the SDK's.
    assert {(e.id, e.current, e.new) for e in status.engines} == {
        ("claude", "2.1.0", "2.2.0"),
        ("opencode", "1.0.0", "1.1.0"),
    }
    assert rig.uv.steps() == ["pip freeze", "venv --relocatable", "pip install", "pip install"]
    pins = rig.uv.calls[-1]
    assert pins[pins.index("--only-binary") + 1] == ":all:"
    assert "claude-agent-sdk==0.3.0" in pins
    assert "openai-codex-cli-bin==0.10.0" in pins
    assert rig.npm.installs() == [
        "opencode-ai@1.1.0",
        "@google/gemini-cli@0.5.0",
        "@github/copilot@1.0.0",
        "@xai-official/grok@1.0.0",
    ]
    assert rig.bus.sent == ["checking", "preparing", "ready"]
    ready = rig.files.load().ready
    assert ready is not None
    assert rig.folders() == [ready]
    manifest = read_manifest(rig.root / ready)
    assert manifest is not None
    assert manifest.base_fingerprint == FINGERPRINT
    assert manifest.packages["opencode"] == "1.1.0"


async def test_a_second_check_while_one_runs_starts_nothing(rig: Rig) -> None:
    rig.latest = registry(NEW_SDK)
    service = rig.service()

    await service.check()
    second = await service.check()
    await service.stop_when_done()

    assert second.state in ("checking", "preparing")
    assert rig.uv.steps().count("venv --relocatable") == 1


async def test_a_prepared_environment_that_matches_is_kept(rig: Rig) -> None:
    rig.latest = registry(NEW_SDK)
    service = await rig.check()
    prepared = rig.files.load().ready
    rig.uv.calls.clear()

    await rig.check(service)

    assert rig.uv.calls == []
    assert rig.files.load().ready == prepared


async def test_a_newer_version_replaces_the_prepared_one(rig: Rig) -> None:
    rig.latest = registry(NEW_SDK)
    service = await rig.check()
    stale = rig.files.load().ready
    rig.latest = registry({**SAME, "claude-agent-sdk": "0.4.0"})

    await rig.check(rig.service())

    ready = rig.files.load().ready
    assert ready not in (None, stale)
    assert rig.folders() == [ready]
    assert (await service.status()).state == "ready"


async def test_a_prepared_engine_update_is_not_offered_while_it_waits(rig: Rig) -> None:
    """B136: a new install's first day keeps its engine updates back, prepared."""
    rig.latest = registry(NEW_SDK)
    await rig.check()

    held = await rig.service(engines_wait=True).status()

    assert (held.state, held.engines) == ("none", [])
    assert rig.files.load().ready is not None
    assert (await rig.service().status()).state == "ready"


@pytest.mark.parametrize(
    "failing",
    [("venv",), ("pip", "install"), "npm", "check"],
    ids=["venv", "install", "npm", "check"],
)
async def test_a_failed_prepare_shows_nothing_and_touches_nothing(
    rig: Rig, failing: tuple[str, ...] | str
) -> None:
    running = make_environment(rig.root, "aaaaaaaaaaaa")
    rig.state(current="aaaaaaaaaaaa", previous=BASE)
    before = rig.files.load()
    rig.latest = registry({**NEW_SDK, "opencode-ai": "1.1.0"})
    if failing == "npm":
        rig.npm.failure = "no network"
    elif failing == "check":
        rig.selfcheck.ok = False
    else:
        rig.uv.fail_on = failing if isinstance(failing, tuple) else None

    service = await rig.check()

    status = await service.status()
    assert status.state == "none"
    assert status.engines == []
    assert status.notice is None
    assert rig.files.load() == before
    assert rig.folders() == [running.name]

    # The next app open tries again.
    rig.uv.fail_on = None
    rig.npm.failure = None
    rig.selfcheck.ok = True
    await rig.check(service)
    assert (await service.status()).state == "ready"


async def test_a_failed_replacement_keeps_the_prepared_update(rig: Rig) -> None:
    rig.latest = registry(NEW_SDK)
    service = await rig.check()
    ready = rig.files.load().ready
    rig.latest = registry({**SAME, "claude-agent-sdk": "0.4.0"})
    rig.selfcheck.ok = False

    await rig.check(service)

    assert rig.files.load().ready == ready
    assert (await service.status()).state == "ready"


async def test_a_machine_with_no_npm_still_gets_its_other_engines(rig: Rig) -> None:
    """Regression: every missing npm engine was fetched, so one failure stopped them all."""
    shutil.rmtree(rig.engines)
    rig.latest = registry({**NEW_SDK, "opencode-ai": "1.1.0"})

    service = await rig.check()

    status = await service.status()
    assert status.state == "ready"
    assert [engine.id for engine in status.engines] == ["claude"]


async def test_a_released_nest_rebuilds_from_its_own_wheel(rig: Rig, tmp_path: Path) -> None:
    """Regression: `nestd` in the frozen list sent uv to PyPI for it."""
    base = tmp_path / "1.0.0"
    (base / "bin").mkdir(parents=True)
    wheel = base / "nestd-1.0.0-py3-none-any.whl"
    wheel.touch()
    rig.state(base_python=str(base / "bin" / "python"))
    rig.uv.freeze = "aiohttp==3.14.4\nnestd @ file:///old/nestd-1.0.0-py3-none-any.whl\n"
    rig.latest = registry(NEW_SDK)

    await rig.check()

    assert str(wheel) in [call[-1] for call in rig.uv.calls]
    ready = rig.files.load().ready
    assert ready is not None
    frozen = (rig.root / ready / "nest-requirements.txt").read_text(encoding="utf-8")
    assert frozen == "aiohttp==3.14.4\n"


async def test_without_uv_or_an_editable_nest_there_are_no_updates(rig: Rig) -> None:
    rig.latest = registry(NEW_SDK)
    rig.uv.freeze = "nestd==0.1.0\naiohttp==3.14.4\n"

    service = await rig.check()

    assert (await service.status()).state == "none"
    assert rig.folders() == []

    async def no_uv(_args: Sequence[str], _cwd: Path, _env: Mapping[str, str]) -> str:
        raise UpdaterUnavailableError("uv was not found")

    rig.uv = no_uv  # pyright: ignore[reportAttributeAccessIssue]
    assert (await (await rig.check()).status()).state == "none"


async def test_a_new_environment_that_crashes_on_import_fails_the_check(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\necho Traceback >&2\nexit 1\n", encoding="utf-8")
    python.chmod(0o755)

    with pytest.raises(PrepareError, match="printed no report"):
        await run_selfcheck(python, tmp_path, tmp_path, {})


def test_the_check_keeps_everything_under_its_throwaway_folder(tmp_path: Path) -> None:
    home = str(tmp_path / "real")
    env = scratch_env(
        {
            "HOME": home,
            "PATH": "/usr/bin",
            "NEST_DATA_DIR": f"{home}/data",
            "CLAUDE_CONFIG_DIR": f"{home}/.claude",
            "CODEX_HOME": f"{home}/.codex",
            "XDG_DATA_HOME": f"{home}/share",
            "ANTHROPIC_API_KEY": "secret",
            "GEMINI_API_KEY": "secret",
            "CLAUDE_CODE_OAUTH_TOKEN": "secret",
        },
        tmp_path / "scratch",
    )

    assert "secret" not in env.values()
    assert env["PATH"].startswith(str(tmp_path / "scratch" / "bin"))
    named = (
        "HOME",
        "NEST_DATA_DIR",
        "NEST_CONFIG_DIR",
        "CLAUDE_CONFIG_DIR",
        "CODEX_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_CONFIG_HOME",
    )
    assert all(env[name].startswith(str(tmp_path / "scratch")) for name in named)


async def test_relaunching_twice_keeps_exactly_one_previous(rig: Rig) -> None:
    for name in ("aaaaaaaaaaaa", "bbbbbbbbbbbb"):
        make_environment(rig.root, name)
    service = rig.service()

    rig.state(ready="aaaaaaaaaaaa")
    await service.relaunch()
    first = rig.files.load()
    assert (first.current, first.previous, first.ready) == ("aaaaaaaaaaaa", BASE, None)
    assert first.trial is True

    rig.state(ready="bbbbbbbbbbbb", trial=False)
    await service.relaunch()
    second = rig.files.load()
    assert (second.current, second.previous) == ("bbbbbbbbbbbb", "aaaaaaaaaaaa")


async def test_a_failed_version_is_not_prepared_again_until_a_newer_one(rig: Rig) -> None:
    rig.latest = registry(NEW_SDK)
    service = await rig.check()
    failed = rig.files.load().ready
    assert failed is not None
    await service.relaunch()
    # The base found it never confirmed.
    state = rig.files.load()
    packages = read_manifest(rig.root / failed)
    assert packages is not None
    rig.files.save(rolled_back(state, packages.packages, "It went back."))
    (rig.root / failed).rename(rig.root / "gone")
    rig.uv.calls.clear()

    await rig.check(service)

    assert rig.uv.calls == []
    assert (await service.status()).state == "none"

    rig.latest = registry({**SAME, "claude-agent-sdk": "0.4.0"})
    await rig.check(rig.service())

    assert (await service.status()).state == "ready"
    assert rig.files.load().refused == []


async def test_undo_brings_the_update_back_with_nothing_to_rebuild(rig: Rig) -> None:
    packages = {**NOW.packages, "claude": "0.3.0"}
    make_environment(rig.root, "aaaaaaaaaaaa", packages=packages)
    rig.state(current="aaaaaaaaaaaa", previous=BASE)
    rig.latest = registry(NEW_SDK)
    service = rig.service()

    await service.undo()
    await rig.check(service)

    status = await service.status()
    assert status.state == "ready"
    assert [(e.id, e.current, e.new) for e in status.engines] == [("claude", "2.1.0", "0.3.0")]
    assert status.can_undo is False
    assert rig.uv.calls == []
    assert rig.files.load().refused == []

    # The restart's cleanup leaves it, and Relaunch goes back to it.
    after_restart = rig.service()
    await after_restart.start()
    await after_restart.settled()
    assert rig.folders() == ["aaaaaaaaaaaa"]

    await after_restart.relaunch()
    state = rig.files.load()
    assert (state.current, state.previous, state.ready) == ("aaaaaaaaaaaa", BASE, None)


async def test_undo_keeps_an_update_already_ready_and_clears_the_one_left(rig: Rig) -> None:
    make_environment(rig.root, "aaaaaaaaaaaa", packages={**NOW.packages, "claude": "0.3.0"})
    make_environment(rig.root, "bbbbbbbbbbbb", packages={**NOW.packages, "claude": "0.4.0"})
    rig.state(current="aaaaaaaaaaaa", previous=BASE, ready="bbbbbbbbbbbb")
    service = rig.service()

    await service.undo()

    assert rig.files.load().ready == "bbbbbbbbbbbb"
    await service.start()
    await service.settled()
    assert rig.folders() == ["bbbbbbbbbbbb"]


async def test_an_undone_update_from_another_base_is_not_offered(rig: Rig) -> None:
    make_environment(rig.root, "aaaaaaaaaaaa", fingerprint="base-before")
    rig.state(current="aaaaaaaaaaaa", previous=BASE)
    service = rig.service()

    await service.undo()

    assert (await service.status()).state == "none"
    with pytest.raises(Exception, match="No update is ready"):
        await service.relaunch()


async def test_every_failed_version_stays_refused(rig: Rig) -> None:
    older = {**NOW.packages, "claude": "0.2.5"}
    newest = {**NOW.packages, "claude": "0.3.0"}
    rig.state(refused=[newest, older])
    rig.latest = registry(NEW_SDK)

    await rig.check()

    assert rig.uv.calls == []


async def test_undo_returns_to_the_previous_environment_once(rig: Rig) -> None:
    make_environment(rig.root, "aaaaaaaaaaaa")
    rig.state(current="bbbbbbbbbbbb", previous="aaaaaaaaaaaa")
    service = rig.service()

    assert (await service.status()).can_undo is True
    await service.undo()

    state = rig.files.load()
    assert (state.current, state.previous) == ("aaaaaaaaaaaa", None)
    assert (await service.status()).can_undo is False


async def test_undo_to_the_base_runs_no_environment(rig: Rig) -> None:
    rig.state(current="aaaaaaaaaaaa", previous=BASE)

    await rig.service().undo()

    assert rig.files.load().current is None


async def test_a_relaunch_refuses_an_environment_that_is_gone(rig: Rig) -> None:
    rig.state(ready="aaaaaaaaaaaa")
    service = rig.service()

    assert (await service.status()).state == "none"
    with pytest.raises(Exception, match="No update is ready"):
        await service.relaunch()


async def test_a_boot_confirms_only_once_its_health_answers(rig: Rig) -> None:
    folder = make_environment(rig.root, "aaaaaaaaaaaa")
    rig.prefix = folder
    rig.state(current="aaaaaaaaaaaa", previous=BASE, trial=True, boots=1)
    ended: list[int] = []
    watch = TrialWatch(30.0, ended.append)
    watch.start()
    rig.answers = [False]
    service = rig.service()
    service.watch = watch

    await service.start()
    assert rig.files.load().boots == 1
    await service.settled()

    state = rig.files.load()
    assert (state.current, state.boots, state.trial) == ("aaaaaaaaaaaa", 0, False)
    assert ended == []
    watch.confirm()


async def test_cleanup_removes_what_nothing_needs_and_nothing_else(rig: Rig) -> None:
    for name in ("aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc", "dddddddddddd"):
        make_environment(rig.root, name)
    (rig.root / "eeeeeeeeeeee.partial").mkdir()
    (rig.root / "not-ours").mkdir()
    rig.state(current="aaaaaaaaaaaa", previous="bbbbbbbbbbbb", ready="cccccccccccc")
    service = rig.service()

    await service.start()
    await service.settled()

    assert rig.folders() == ["aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc", "not-ours"]
    assert rig.files.path.exists()


async def test_cleanup_keeps_the_engine_versions_environments_need(rig: Rig) -> None:
    packages = {**NOW.packages, "opencode": "1.2.0"}
    make_environment(rig.root, "aaaaaaaaaaaa", packages=packages)
    make_environment(rig.root, "bbbbbbbbbbbb", packages={**NOW.packages, "opencode": "1.1.0"})
    rig.state(current="aaaaaaaaaaaa", previous="bbbbbbbbbbbb")
    folder = rig.engines / "opencode"
    assert OPENCODE.version is not None
    versions = ("1.0.9", "1.1.0", "1.2.0", OPENCODE.version)
    for version in versions:
        (folder / version).mkdir(parents=True)
    (folder / "probe").mkdir()
    (folder / ".1.3.0.partial").mkdir()
    service = rig.service()

    await service.start()
    await service.settled()

    assert sorted(entry.name for entry in folder.iterdir()) == sorted(
        [".1.3.0.partial", "1.1.0", "1.2.0", OPENCODE.version, "probe"]
    )


async def test_a_prepare_under_way_keeps_its_half_made_folder(rig: Rig) -> None:
    rig.latest = registry(NEW_SDK)
    gate = asyncio.Event()
    filled = asyncio.Event()
    fake = rig.uv

    async def waiting(args: Sequence[str], cwd: Path, env: Mapping[str, str]) -> str:
        answer = await fake(args, cwd, env)
        if args[0] == "venv":
            filled.set()
            await gate.wait()
        return answer

    rig.uv = waiting  # pyright: ignore[reportAttributeAccessIssue]
    service = rig.service()
    await service.check()
    await filled.wait()

    await service.start()
    await service.settled()
    assert len(rig.folders()) == 1

    gate.set()
    await service.stop_when_done()
    assert (await service.status()).state == "ready"


def test_the_acp_list_follows_the_environment_it_runs_in(tmp_path: Path) -> None:
    folder = make_environment(
        tmp_path, "aaaaaaaaaaaa", packages={"opencode": "9.9.9", "claude": "1.0"}
    )

    engines = in_environment((OPENCODE, GEMINI), folder)

    assert [engine.version for engine in engines] == ["9.9.9", GEMINI.version]
    assert in_environment((OPENCODE,), tmp_path / "base") == (OPENCODE,)
    assert replace(OPENCODE, version="9.9.9") == engines[0]


async def test_stop_kills_a_prepare_and_leaves_no_half_made_folder(rig: Rig) -> None:
    rig.latest = registry(NEW_SDK)
    filled = asyncio.Event()
    fake = rig.uv

    async def stuck(args: Sequence[str], cwd: Path, env: Mapping[str, str]) -> str:
        answer = await fake(args, cwd, env)
        if args[0] == "venv":
            filled.set()
            await asyncio.Event().wait()
        return answer

    rig.uv = stuck  # pyright: ignore[reportAttributeAccessIssue]
    service = rig.service()
    await service.check()
    await filled.wait()

    await service.stop()

    assert rig.folders() == []
    assert rig.files.load().ready is None
