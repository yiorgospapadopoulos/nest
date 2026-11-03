"""B107: a pinned engine is fetched into Nest's own folder, never globally, with no
package script, and only a whole install counts as installed.
"""

from collections.abc import Mapping
from pathlib import Path

from nestd.engine.acp_install import PROBE_FOLDER, EngineInstall, InstallState
from nestd.providers.acp_engines import CURSOR, GEMINI, OPENCODE
from tests.acp_engine_support import FakeNpm, preinstall, program_path


def _env() -> Mapping[str, str]:
    return {"PATH": "/nowhere"}


async def _env_source() -> Mapping[str, str]:
    return _env()


def _install(tmp_path: Path, npm: FakeNpm, seen: list[InstallState] | None = None) -> EngineInstall:
    async def changed(state: InstallState) -> None:
        if seen is not None:
            seen.append(state)

    return EngineInstall(
        OPENCODE, tmp_path / "engines", npm, _env_source, tmp_path / "home", on_change=changed
    )


async def test_a_missing_engine_installs_its_pinned_version_and_drops_old_ones(
    tmp_path: Path,
) -> None:
    npm = FakeNpm()
    seen: list[InstallState] = []
    install = _install(tmp_path, npm, seen)
    folder = tmp_path / "engines" / "opencode"
    (folder / "1.0.0" / "node_modules").mkdir(parents=True)
    (folder / PROBE_FOLDER).mkdir()
    (folder / "system-settings.json").write_text("{}", encoding="utf-8")

    before = await install.current()
    after = await install.install()

    assert before.state == "not_installed"
    assert [state.state for state in seen] == ["installing", "ready"]
    assert after.state == "ready"
    assert after.version == "1.19.5"
    # The platform package's binary: the `.bin` entry is a placeholder its script replaces.
    assert after.program == program_path(OPENCODE, folder / "1.19.5")
    args, _cwd, _env = npm.calls[0]
    assert args[0] == "install"
    assert "--ignore-scripts" in args
    assert "-g" not in args
    assert "--global" not in args
    assert args[-1] == "opencode-ai@1.19.5"
    assert sorted(entry.name for entry in folder.iterdir()) == [
        "1.19.5",
        PROBE_FOLDER,
        "system-settings.json",
    ]
    # Quick when it is there: npm is not run again.
    assert (await install.install()).state == "ready"
    assert len(npm.calls) == 1


async def test_a_failed_npm_leaves_nothing_half_installed_and_says_why(tmp_path: Path) -> None:
    npm = FakeNpm()
    npm.failure = "npm failed (1): network down"
    install = _install(tmp_path, npm)

    failed = await install.install()

    assert failed.state == "install_failed"
    assert failed.detail == "npm failed (1): network down"
    assert (await install.current()).state == "install_failed"
    assert [entry.name for entry in (tmp_path / "engines" / "opencode").iterdir()] == []

    npm.failure = None
    assert (await install.install()).state == "ready"


async def test_an_engine_installed_earlier_is_ready_without_npm(tmp_path: Path) -> None:
    npm = FakeNpm()
    program = preinstall(tmp_path / "engines", GEMINI)
    install = EngineInstall(GEMINI, tmp_path / "engines", npm, _env_source, tmp_path)

    state = await install.current()

    assert (state.state, state.program) == ("ready", program)
    assert npm.calls == []


async def test_the_users_own_engine_is_found_where_its_installer_puts_it(tmp_path: Path) -> None:
    home = tmp_path / "home"
    install = EngineInstall(CURSOR, tmp_path / "engines", FakeNpm(), _env_source, home)
    missing = await install.current()
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "agent").write_text("#!/bin/sh\n", encoding="utf-8")

    found = await install.current()

    assert missing.state == "not_installed"
    assert install.start() is False
    assert (found.state, found.program) == ("ready", home / ".local" / "bin" / "agent")
