"""What would hurt in updating Nest itself: a bad download reaching the install, a release
not signed by Nest's key being trusted, a failed update leaving the user on nothing, and a
checkout (the user's own Nest) being updated.
"""

import base64
import hashlib
import json
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO, Literal

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

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
    note_stop,
    platform_key,
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


def _public(key: ec.EllipticCurvePrivateKey) -> str:
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(der).decode()


type Signing = Literal["good", "missing", "other key", "changed after signing"]


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
        loaded = not self.calls or self.calls[-1] != "stop"
        return ServiceStatus(installed=True, loaded=loaded, detail="")


class SlowToStop(Service):
    """`launchctl bootout` returns while the old daemon is still exiting, its database open."""

    def __init__(self, database: Path, polls: int) -> None:
        super().__init__()
        self.database = database
        self.polls = polls
        self.seen_while_running: list[str] = []
        self.handle: BinaryIO | None = None

    def stop(self) -> None:
        super().stop()
        self.handle = self.database.open("r+b")

    def status(self) -> ServiceStatus:
        if self.calls[-1] == "stop" and self.polls > 0:
            self.polls -= 1
            self.seen_while_running.append(_value(self.database))
            return ServiceStatus(installed=True, loaded=True, detail="")
        return super().status()


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
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.signing: Signing = "good"

    def _latest(self) -> dict[str, object]:
        kinds = (("wheel", "any"), ("requirements", "any"), ("app", platform_key("macos")))
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

    def _manifest(self) -> bytes:
        return json.dumps(self._latest()).encode()

    def _signature(self) -> httpx.Response:
        if self.signing == "missing":
            return httpx.Response(404)
        key = ec.generate_private_key(ec.SECP256R1()) if self.signing == "other key" else self.key
        return httpx.Response(200, content=key.sign(self._manifest(), ec.ECDSA(hashes.SHA256())))

    def _answer(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        if name == "latest.json.sig":
            return self._signature()
        if name == "latest.json":
            if self.signing != "changed after signing":
                return httpx.Response(200, content=self._manifest())
            # A swapped app with its sha256 changed to match: only the signature catches it.
            good = hashlib.sha256(self.files["Nest.zip"]).hexdigest()
            swapped = hashlib.sha256(b"tampered").hexdigest()
            self.bad = "Nest.zip"
            return httpx.Response(
                200, content=self._manifest().replace(good.encode(), swapped.encode())
            )
        return httpx.Response(200, content=b"tampered" if name == self.bad else self.files[name])

    def updater(self, *, packaged: bool = True, running: str = "1.0.0") -> AppUpdater:
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
            running=running,
            watcher=watcher,
            release_keys=(_public(self.key),),
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


@pytest.mark.parametrize(
    ("signing", "message"),
    [
        ("missing", "has no signature"),
        ("other key", "not signed by Nest's release key"),
        ("changed after signing", "not signed by Nest's release key"),
    ],
)
async def test_a_release_not_signed_by_nests_key_is_refused_before_anything_runs(
    rig: Rig, signing: Signing, message: str
) -> None:
    rig.signing = signing

    with pytest.raises(PrepareError, match=message):
        await rig.updater().check_and_prepare(_nothing)

    assert rig.uv_calls == []
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


def _trial(
    rig: Rig,
    service: Service,
    answers: list[str | None],
    *,
    old: str = "1.0.0",
    new: str = "2.0.0",
    backup: str = "nest.db.before-2.0.0",
) -> Trial:
    clock = [0.0]

    def now() -> float:
        clock[0] += 1.0
        return clock[0]

    def answer(_port: int) -> str | None:
        return answers.pop(0) if answers else None

    return Trial(
        rig.paths,
        service,
        8765,
        old,
        new,
        rig.paths.data_dir / "backups-update" / backup,
        version_on=answer,
        now=now,
        pause=lambda _: None,
        seconds=10.0,
        settle_seconds=5.0,
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


async def test_a_new_version_that_crashes_soon_after_answering_is_undone(rig: Rig) -> None:
    """B159 R12: one health answer confirmed it, and launchd restarted it forever after."""
    updater = rig.updater()
    await updater.check_and_prepare(_nothing)
    await updater.relaunch(8765)
    note_start(rig.daemon, "2.0.0")
    service = Service()
    trial = _trial(rig, service, ["2.0.0"])

    def crash(_seconds: float) -> None:
        note_start(rig.daemon, "2.0.0")

    assert not watch(replace(trial, pause=crash, settle_seconds=100.0))

    assert service.calls == ["stop", "install"]
    assert (rig.daemon / CURRENT).resolve().name == "1.0.0"
    assert _value(rig.paths.db_path) == "before"
    assert read_state(rig.daemon).notice == (
        "Nest 2.0.0 kept crashing, so Nest went back to 1.0.0 and to your chats as they were"
        " before the update. Anything done since the update is lost."
    )


async def test_restarts_after_clean_stops_are_no_crashes(rig: Rig) -> None:
    """B159 recheck 1: Settings > Restart three times soon after an update rolled it back."""
    updater = rig.updater()
    await updater.check_and_prepare(_nothing)
    await updater.relaunch(8765)
    note_start(rig.daemon, "2.0.0")
    service = Service()
    trial = _trial(rig, service, ["2.0.0"])

    def restart(_seconds: float) -> None:
        note_stop(rig.daemon, "2.0.0")
        note_start(rig.daemon, "2.0.0")

    assert watch(replace(trial, pause=restart, settle_seconds=100.0))

    assert service.calls == []
    assert (rig.daemon / CURRENT).resolve().name == "2.0.0"


async def test_the_database_is_put_back_only_once_the_old_daemon_has_exited(rig: Rig) -> None:
    """B159 R13: the backup was copied over the database while the failed daemon still ran."""
    updater = rig.updater()
    await updater.check_and_prepare(_nothing)
    await updater.relaunch(8765)
    _database(rig.paths.db_path, 48, "migrated")
    service = SlowToStop(rig.paths.db_path, polls=3)

    assert not watch(_trial(rig, service, []))

    assert service.seen_while_running == ["migrated"] * 3
    assert service.handle is not None
    # A last write from the exiting daemon lands in the file it had open, not the restored one.
    service.handle.write(b"x" * 4096)
    service.handle.close()
    assert _value(rig.paths.db_path) == "before"
    assert service.calls == ["stop", "install"]


async def test_undo_is_watched_like_an_update(rig: Rig) -> None:
    """B159 R12: Undo started no watcher, so an old version that failed to start stayed down."""
    await rig.updater().check_and_prepare(_nothing)
    await rig.updater().relaunch(8765)
    # 1.0.0's starts from before the update must not count against it now.
    for _ in range(3):
        note_start(rig.daemon, "1.0.0")
    updater = rig.updater(running="2.0.0")

    await updater.undo(8765)

    assert rig.watchers[-1] == ("2.0.0", "1.0.0")
    backup = "nest.db.before-undo-1.0.0"
    assert _value(rig.paths.data_dir / "backups-update" / backup) == "before"
    service = Service()
    trial = _trial(rig, service, [None, "1.0.0"], old="2.0.0", new="1.0.0", backup=backup)

    assert watch(trial)

    assert service.calls == []
    assert (rig.daemon / CURRENT).resolve().name == "1.0.0"


async def test_a_failed_undo_goes_back_to_a_version_that_is_still_there(rig: Rig) -> None:
    await rig.updater().check_and_prepare(_nothing)
    await rig.updater().relaunch(8765)
    await rig.updater(running="2.0.0").undo(8765)
    # 1.0.0 starts and clears what it does not need, then stops answering.
    rig.updater().clear_unused()
    trial = _trial(rig, Service(), [], old="2.0.0", new="1.0.0", backup="nest.db.before-undo-1.0.0")

    assert not watch(trial)

    assert (rig.daemon / CURRENT).resolve().name == "2.0.0"
    assert (rig.daemon / "2.0.0").is_dir()


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
        await updater.undo(8765)
    assert (rig.daemon / CURRENT).resolve().name == "2.0.0"


async def test_undo_moves_current_back(rig: Rig) -> None:
    updater = rig.updater()
    await updater.check_and_prepare(_nothing)
    await updater.relaunch(8765)

    await updater.undo(8765)

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
