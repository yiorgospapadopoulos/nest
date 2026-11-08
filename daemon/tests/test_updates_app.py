"""What would hurt in updating Nest itself: a bad download reaching the install, a failed
update leaving the user on nothing, and a checkout (the user's own Nest) being updated.
"""

import hashlib
import json
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from nestd.errors import ConflictError
from nestd.paths import AppPaths
from nestd.service.base import ServiceStatus
from nestd.updates.app import (
    APP_FILE,
    CURRENT,
    AppState,
    AppUpdate,
    AppUpdater,
    back_up_database,
    database_version,
    note_start,
    point_current,
    read_state,
    save_state,
    without_apple_stubs,
)
from nestd.updates.build import PrepareError, released_wheel
from nestd.updates.selfcheck_report import SelfcheckReport
from nestd.updates.watcher import Trial, watch


async def _nothing() -> None:
    return None


def _database(path: Path, version: int, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE IF NOT EXISTS t (value TEXT)")
    connection.execute("DELETE FROM t")
    connection.execute("INSERT INTO t VALUES (?)", (text,))
    connection.execute(f"PRAGMA user_version = {version}")
    connection.commit()
    connection.close()


def _value(path: Path) -> str:
    connection = sqlite3.connect(path)
    row = connection.execute("SELECT value FROM t").fetchone()
    connection.close()
    return str(row[0])


class Service:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.unit_path = Path("/nowhere")

    def install(self) -> None:
        self.calls.append("install")

    def remove_legacy(self) -> bool:
        return False

    def stop(self) -> None:
        self.calls.append("stop")

    def uninstall(self) -> None:
        self.calls.append("uninstall")

    def status(self) -> ServiceStatus:
        return ServiceStatus(installed=True, loaded=True, detail="")


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
        self.daemon = self.paths.daemon_dir
        (self.daemon / "1.0.0").mkdir(parents=True)
        (self.daemon / "1.0.0" / APP_FILE).write_bytes(b"old app")
        point_current(self.daemon, "1.0.0")
        _database(self.paths.db_path, 47, "before")
        self.files = {"nestd-2.0.0-py3-none-any.whl": b"wheel", "req": b"r", "Nest.zip": b"app"}
        self.bad: str | None = None
        self.version = "2.0.0"
        self.report_ok = True
        self.uv_calls: list[list[str]] = []
        self.watchers: list[tuple[str, str]] = []

    def _latest(self) -> dict[str, object]:
        kinds = (("wheel", "any"), ("requirements", "any"), ("app", "macos-arm64"))
        return {
            "version": self.version,
            "notes": "New things",
            "files": [
                {
                    "platform": platform,
                    "kind": kind,
                    "name": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
                for (name, content), (kind, platform) in zip(self.files.items(), kinds, strict=True)
            ],
        }

    def _answer(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        if name == "latest.json":
            return httpx.Response(200, content=json.dumps(self._latest()))
        return httpx.Response(200, content=b"tampered" if name == self.bad else self.files[name])

    def updater(self, *, packaged: bool = True) -> AppUpdater:
        async def uv(args: Sequence[str], _cwd: Path, _env: Mapping[str, str]) -> str:
            self.uv_calls.append(list(args))
            if args[0] == "venv":
                (Path(args[-1]) / "bin").mkdir(parents=True)
            return ""

        async def selfcheck(
            _python: Path, _engines: Path, _cwd: Path, _env: Mapping[str, str]
        ) -> SelfcheckReport:
            return SelfcheckReport(ok=self.report_ok, daemon=self.report_ok, engines=[])

        async def env() -> Mapping[str, str]:
            return {"NEST_RELEASE_URL": "http://release.test"}

        def watcher(_daemon: Path, _port: int, old: str, new: str, _backup: Path) -> None:
            self.watchers.append((old, new))

        return AppUpdater(
            paths=self.paths,
            platform="macos",
            packaged=packaged,
            uv=uv,
            selfcheck=selfcheck,
            env=env,
            transport=httpx.MockTransport(self._answer),
            running="1.0.0",
            watcher=watcher,
        )


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


async def test_a_checkout_never_looks_for_updates(rig: Rig) -> None:
    updater = rig.updater(packaged=False)

    assert not await updater.check_and_prepare(_nothing)
    assert rig.uv_calls == []
    assert updater.app_file() is None


async def test_a_newer_release_is_built_beside_the_running_one(rig: Rig) -> None:
    updater = rig.updater()

    assert await updater.check_and_prepare(_nothing)

    assert read_state(rig.daemon).ready == AppUpdate(version="2.0.0", notes="New things")
    assert (rig.daemon / "2.0.0" / APP_FILE).read_bytes() == b"app"
    assert (rig.daemon / CURRENT).resolve().name == "1.0.0"


@pytest.mark.parametrize("version", ["1.0.0", "0.9.0", "2.0.0-rc1"])
async def test_only_a_newer_stable_release_is_prepared(rig: Rig, version: str) -> None:
    rig.version = version

    assert not await rig.updater().check_and_prepare(_nothing)
    assert rig.uv_calls == []


async def test_a_bad_sha256_leaves_nothing_behind(rig: Rig) -> None:
    rig.bad = "Nest.zip"

    with pytest.raises(PrepareError, match="sha256"):
        await rig.updater().check_and_prepare(_nothing)

    assert sorted(entry.name for entry in rig.daemon.iterdir()) == ["1.0.0", CURRENT]
    assert read_state(rig.daemon).ready is None


async def test_a_build_that_fails_its_check_is_never_offered(rig: Rig) -> None:
    rig.report_ok = False

    with pytest.raises(PrepareError):
        await rig.updater().check_and_prepare(_nothing)

    assert not (rig.daemon / "2.0.0").exists()
    assert read_state(rig.daemon).ready is None


async def test_relaunch_backs_up_starts_the_watcher_then_moves_current(rig: Rig) -> None:
    updater = rig.updater()
    await updater.check_and_prepare(_nothing)

    await updater.relaunch(8765)

    assert rig.watchers == [("1.0.0", "2.0.0")]
    assert (rig.daemon / CURRENT).resolve().name == "2.0.0"
    assert _value(rig.paths.data_dir / "backups-update" / "nest.db.before-2.0.0") == "before"
    assert read_state(rig.daemon).ready is None
    assert read_state(rig.daemon).previous == "1.0.0"
    # The apps read this while the daemon is down, to say an update is under way.
    updating = read_state(rig.daemon).updating
    assert updating is not None
    assert (updating.from_version, updating.to_version) == ("1.0.0", "2.0.0")


def _trial(rig: Rig, service: Service, answers: list[str | None]) -> Trial:
    clock = [0.0]

    def now() -> float:
        clock[0] += 1.0
        return clock[0]

    def answer(_port: int) -> str | None:
        return answers.pop(0) if answers else None

    backup = rig.paths.data_dir / "backups-update" / "nest.db.before-2.0.0"
    return Trial(
        rig.paths,
        service,
        8765,
        "1.0.0",
        "2.0.0",
        backup,
        version_on=answer,
        now=now,
        pause=lambda _: None,
        seconds=10.0,
    )


async def test_a_new_version_that_answers_is_left_alone(rig: Rig) -> None:
    updater = rig.updater()
    await updater.check_and_prepare(_nothing)
    await updater.relaunch(8765)
    service = Service()

    assert watch(_trial(rig, service, ["1.0.0", None, "2.0.0"]))

    assert service.calls == []
    assert (rig.daemon / CURRENT).resolve().name == "2.0.0"
    assert read_state(rig.daemon).updating is None


async def test_a_new_version_that_never_answers_puts_everything_back(rig: Rig) -> None:
    updater = rig.updater()
    await updater.check_and_prepare(_nothing)
    await updater.relaunch(8765)
    # The failed version migrated the database and left a write-ahead log.
    _database(rig.paths.db_path, 48, "migrated")
    rig.paths.db_path.with_name("nest.db-wal").write_bytes(b"newer pages")
    service = Service()

    assert not watch(_trial(rig, service, []))

    assert (rig.daemon / CURRENT).resolve().name == "1.0.0"
    assert _value(rig.paths.db_path) == "before"
    assert database_version(rig.paths.db_path) == 47
    assert not rig.paths.db_path.with_name("nest.db-wal").exists()
    assert not (rig.daemon / "2.0.0").exists()
    assert service.calls == ["stop", "install"]
    state = read_state(rig.daemon)
    assert state.notice == (
        "Nest 2.0.0 didn't respond when it started, so Nest went back to 1.0.0. "
        "Your chats are safe."
    )
    assert state.refused == ["2.0.0"]


async def test_a_failed_update_gives_back_the_undo_from_before_it(rig: Rig) -> None:
    """B136: after a failed update, the update before it could no longer be undone."""
    (rig.daemon / "0.9.0").mkdir()
    save_state(rig.daemon, AppState(previous="0.9.0", previous_schema=47))
    updater = rig.updater()
    await updater.check_and_prepare(_nothing)
    await updater.relaunch(8765)
    # While it is on trial, its start clears what it does not need, but not the old Undo.
    updater.clear_unused()

    assert not watch(_trial(rig, Service(), []))

    state = read_state(rig.daemon)
    assert (state.previous, state.previous_schema) == ("0.9.0", 47)
    assert (rig.daemon / "0.9.0").is_dir()


async def test_a_new_version_that_keeps_crashing_is_undone_without_waiting(rig: Rig) -> None:
    """Regression: a crashing update left the user 2 minutes with nothing to read."""
    updater = rig.updater()
    await updater.check_and_prepare(_nothing)
    await updater.relaunch(8765)
    for _ in range(3):
        note_start(rig.daemon, "2.0.0")
    service = Service()
    trial = _trial(rig, service, [])

    assert not watch(replace(trial, seconds=1000.0))

    assert service.calls == ["stop", "install"]
    assert (rig.daemon / CURRENT).resolve().name == "1.0.0"
    assert read_state(rig.daemon).updating is None
    notice = read_state(rig.daemon).notice
    assert notice is not None
    assert "kept crashing when it started" in notice


async def test_a_release_that_failed_is_not_offered_again(rig: Rig) -> None:
    save_state(rig.daemon, AppState(refused=["2.0.0"]))

    assert not await rig.updater().check_and_prepare(_nothing)


async def test_undo_needs_the_database_to_be_as_it_was(rig: Rig) -> None:
    updater = rig.updater()
    await updater.check_and_prepare(_nothing)
    await updater.relaunch(8765)

    assert updater.can_undo()

    _database(rig.paths.db_path, 48, "migrated")

    assert not updater.can_undo()
    with pytest.raises(ConflictError):
        await updater.undo()
    assert (rig.daemon / CURRENT).resolve().name == "2.0.0"


async def test_undo_moves_current_back(rig: Rig) -> None:
    updater = rig.updater()
    await updater.check_and_prepare(_nothing)
    await updater.relaunch(8765)

    await updater.undo()

    assert (rig.daemon / CURRENT).resolve().name == "1.0.0"
    assert not updater.can_undo()


def test_a_backup_holds_what_the_write_ahead_log_holds(tmp_path: Path) -> None:
    database = tmp_path / "nest.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("CREATE TABLE t (value TEXT)")
    connection.execute("INSERT INTO t VALUES ('only in the log')")
    connection.commit()
    backup = tmp_path / "backups" / "copy"

    back_up_database(database, backup)
    connection.close()

    assert _value(backup) == "only in the log"


def test_clearing_keeps_the_running_previous_and_ready_versions(rig: Rig) -> None:
    for name in ("0.9.0", "2.0.0", "3.0.0", "3.0.0.partial", "backups"):
        (rig.daemon / name).mkdir()
    update = AppUpdate(version="3.0.0", notes="")
    save_state(rig.daemon, AppState(previous="0.9.0", ready=update))

    rig.updater().clear_unused()

    names = sorted(entry.name for entry in rig.daemon.iterdir())
    assert names == ["0.9.0", "1.0.0", "3.0.0", "backups", CURRENT, "update.json"]


def test_a_released_base_keeps_its_wheel_a_checkout_has_none(tmp_path: Path) -> None:
    base = tmp_path / "1.0.0"
    (base / "bin").mkdir(parents=True)

    assert released_wheel(str(base / "bin" / "python")) is None

    wheel = base / "nestd-1.0.0-py3-none-any.whl"
    wheel.touch()

    assert released_wheel(str(base / "bin" / "python")) == wheel


@pytest.mark.skipif(sys.platform != "darwin", reason="Apple's stand-in tools are on macOS only")
def test_uv_never_meets_apples_stand_in_tools_on_a_mac_without_them(tmp_path: Path) -> None:
    """Regression: installing Python opened Apple's developer tools window on a clean Mac."""
    folder = tmp_path / "bin"
    folder.mkdir()
    uv = folder / "uv"
    uv.write_text("#!/bin/sh\n", encoding="utf-8")
    uv.chmod(0o755)
    env = {"PATH": f"{folder}:/usr/bin:/bin", "HOME": "/home/me"}

    assert without_apple_stubs(env, installed=lambda: False)["PATH"] == str(folder)
    assert without_apple_stubs(env, installed=lambda: True) == env
