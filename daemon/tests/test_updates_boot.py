"""The switch at the start of `nestd serve`: whatever the state, the daemon comes up, and a
new environment that did not start is left behind.
"""

import threading
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from nestd.updates.boot import SWITCHED_ENV, Boot, TrialWatch, switch_environment
from nestd.updates.environments import python_of
from nestd.updates.state import (
    BASE,
    BOOT_LIMIT,
    STATE_NAME,
    StateFile,
    UpdateState,
    confirmed,
)
from tests.updates_support import FINGERPRINT, NOW, make_environment


@dataclass
class FakeExec:
    root: Path
    calls: list[tuple[str, list[str], dict[str, str]]] = field(
        default_factory=list[tuple[str, list[str], dict[str, str]]]
    )
    # What the state said when this process was replaced.
    state_then: UpdateState | None = None
    failure: OSError | None = None

    def __call__(self, program: str, args: list[str], env: Mapping[str, str]) -> None:
        self.calls.append((program, args, dict(env)))
        self.state_then = StateFile(self.root).load()
        if self.failure is not None:
            raise self.failure


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "environments"
        self.root.mkdir()
        self.files = StateFile(self.root)
        self.exec = FakeExec(self.root)
        self.boot = Boot(
            root=self.root,
            prefix=tmp_path / "base",
            executable="/base/bin/python",
            env={"PATH": "/bin"},
            exec_program=self.exec,
            fingerprint=lambda: FINGERPRINT,
        )

    def state(self, **fields: object) -> None:
        self.files.save(UpdateState.model_validate(fields))

    def start(self, boot: Boot | None = None) -> TrialWatch | None:
        return switch_environment(boot or self.boot, ["serve", "--port", "9100"])


def _no_end(_code: int) -> None:
    pytest.fail("the daemon was ended")


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def test_a_boot_is_counted_before_the_base_hands_over(rig: Rig) -> None:
    folder = make_environment(rig.root, "aaaaaaaaaaaa")
    rig.state(current="aaaaaaaaaaaa", previous=BASE, trial=True)

    rig.start()

    python = str(python_of(folder))
    program, args, env = rig.exec.calls[0]
    assert program == python
    assert args == [python, "-m", "nestd", "serve", "--port", "9100"]
    assert env[SWITCHED_ENV] == "aaaaaaaaaaaa"
    assert rig.exec.state_then is not None
    assert rig.exec.state_then.boots == 1
    assert rig.exec.state_then.base_python == "/base/bin/python"


def test_an_update_that_never_confirmed_is_left_after_one_boot(rig: Rig) -> None:
    packages = {**NOW.packages, "claude": "0.3.0"}
    make_environment(rig.root, "aaaaaaaaaaaa", packages=packages, summary="Claude Code 2.2.0")
    previous = make_environment(rig.root, "bbbbbbbbbbbb")
    rig.state(current="aaaaaaaaaaaa", previous="bbbbbbbbbbbb", trial=True, boots=1)

    rig.start()

    state = rig.files.load()
    assert state.current == "bbbbbbbbbbbb"
    assert state.previous is None
    assert state.trial is False
    assert state.boots == 1
    assert state.refused == [packages]
    assert state.notice == (
        "The update to Claude Code 2.2.0 did not start, so Nest went back to the previous engines."
    )
    assert rig.exec.calls[0][0] == str(python_of(previous))


def test_a_failed_update_from_the_base_goes_back_to_the_base(rig: Rig) -> None:
    make_environment(rig.root, "aaaaaaaaaaaa")
    rig.state(current="aaaaaaaaaaaa", previous=BASE, trial=True, boots=1)

    rig.start()

    state = rig.files.load()
    assert state.current is None
    assert state.previous is None
    assert state.notice is not None
    assert rig.exec.calls == []


def test_an_environment_that_keeps_crashing_ends_on_the_previous_one(rig: Rig) -> None:
    """A deploy broke it: the fingerprint is the same, so only the count can tell."""
    packages = {**NOW.packages, "claude": "0.3.0"}
    make_environment(rig.root, "aaaaaaaaaaaa", packages=packages, summary="Claude Code 2.2.0")
    make_environment(rig.root, "bbbbbbbbbbbb")
    rig.state(current="aaaaaaaaaaaa", previous="bbbbbbbbbbbb")

    for _ in range(BOOT_LIMIT):
        rig.start()
    still_trying = rig.files.load()
    rig.start()

    assert (still_trying.current, still_trying.boots) == ("aaaaaaaaaaaa", BOOT_LIMIT)
    state = rig.files.load()
    assert (state.current, state.previous, state.boots) == ("bbbbbbbbbbbb", None, 1)
    assert state.refused == [packages]
    assert state.notice == (
        "Nest could not start with Claude Code 2.2.0, so it went back to the previous engines."
    )


def test_a_crash_loop_always_ends_on_the_base(rig: Rig) -> None:
    make_environment(rig.root, "aaaaaaaaaaaa")
    make_environment(rig.root, "bbbbbbbbbbbb")
    rig.state(current="aaaaaaaaaaaa", previous="bbbbbbbbbbbb")

    for _ in range(2 * BOOT_LIMIT + 2):
        rig.start()

    state = rig.files.load()
    assert (state.current, state.previous, state.boots) == (None, None, 0)
    assert len(rig.exec.calls) == 2 * BOOT_LIMIT


def test_restarts_after_good_boots_never_add_up(rig: Rig) -> None:
    make_environment(rig.root, "aaaaaaaaaaaa")
    rig.state(current="aaaaaaaaaaaa", previous=BASE)

    for _ in range(2 * BOOT_LIMIT):
        rig.start()
        rig.files.save(confirmed(rig.files.load()))

    state = rig.files.load()
    assert (state.current, state.previous, state.boots) == ("aaaaaaaaaaaa", BASE, 0)
    assert state.notice is None


@pytest.mark.parametrize("damage", ["folder", "python", "manifest"])
def test_a_broken_environment_runs_the_base(rig: Rig, damage: str) -> None:
    folder = make_environment(rig.root, "aaaaaaaaaaaa")
    if damage == "folder":
        python_of(folder).unlink()
        (folder / "nest-engines.json").unlink()
        python_of(folder).parent.rmdir()
        folder.rmdir()
    elif damage == "python":
        python_of(folder).unlink()
    else:
        (folder / "nest-engines.json").write_text("{", encoding="utf-8")
    rig.state(current="aaaaaaaaaaaa", previous=BASE)

    assert rig.start() is None

    assert rig.exec.calls == []
    assert rig.files.load().current is None


def test_an_unreadable_state_runs_the_base(rig: Rig) -> None:
    (rig.root / STATE_NAME).write_text("not json", encoding="utf-8")

    assert rig.start() is None

    assert rig.exec.calls == []
    assert rig.files.load().base_fingerprint == FINGERPRINT


def test_a_state_that_cannot_be_written_never_stops_the_daemon(rig: Rig) -> None:
    (rig.root / STATE_NAME).mkdir()

    assert rig.start() is None

    assert rig.exec.calls == []


def test_an_environment_that_cannot_start_goes_back_at_once(rig: Rig) -> None:
    make_environment(rig.root, "aaaaaaaaaaaa")
    rig.state(current="aaaaaaaaaaaa", previous=BASE, trial=True)
    rig.exec.failure = PermissionError("no")

    assert rig.start() is None

    state = rig.files.load()
    assert state.current is None
    assert state.trial is False
    assert state.notice is not None


def test_a_deployed_base_stays_on_the_base_and_forgets_older_environments(rig: Rig) -> None:
    for name in ("aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"):
        make_environment(rig.root, name, fingerprint="an older base")
    rig.state(current="aaaaaaaaaaaa", previous="bbbbbbbbbbbb", ready="cccccccccccc")

    rig.start()

    state = rig.files.load()
    assert (state.current, state.previous, state.ready) == (None, None, None)
    assert rig.exec.calls == []


def test_the_environment_itself_never_switches_again(rig: Rig) -> None:
    folder = make_environment(rig.root, "aaaaaaaaaaaa")
    rig.state(current="aaaaaaaaaaaa", previous=BASE)

    watch = rig.start(replace(rig.boot, prefix=folder, watch=lambda: TrialWatch(30.0, _no_end)))

    assert rig.exec.calls == []
    assert watch is not None
    watch.confirm()


def test_a_process_that_already_switched_never_switches_again(rig: Rig) -> None:
    make_environment(rig.root, "aaaaaaaaaaaa")
    rig.state(current="aaaaaaaaaaaa", previous=BASE)

    rig.start(replace(rig.boot, env={SWITCHED_ENV: "aaaaaaaaaaaa"}))

    assert rig.exec.calls == []


@pytest.mark.parametrize("trial", [True, False])
def test_every_boot_of_an_environment_is_watched_until_it_confirms(rig: Rig, trial: bool) -> None:
    folder = make_environment(rig.root, "aaaaaaaaaaaa")
    rig.state(current="aaaaaaaaaaaa", previous=BASE, trial=trial, boots=1)
    ended = threading.Event()

    watch = rig.start(
        replace(
            rig.boot,
            prefix=folder,
            watch=lambda: TrialWatch(0.01, lambda _code: ended.set()),
        )
    )

    assert watch is not None
    assert ended.wait(5)


def test_a_confirmed_daemon_is_left_alone() -> None:
    ended = threading.Event()
    watch = TrialWatch(0.2, lambda _code: ended.set())

    watch.start()
    watch.confirm()

    assert not ended.wait(0.4)
