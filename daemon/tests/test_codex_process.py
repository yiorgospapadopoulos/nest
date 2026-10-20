import sys
from pathlib import Path

import pytest

from nestd.providers import codex_process
from nestd.providers.codex_process import (
    CODEX_HOME_ENV,
    CodexBinary,
    CodexLaunch,
    ProcessTransport,
    app_server_launch,
    bundled_binary,
    spawn,
)

# Echoes each stdin line back on stdout and says hello on stderr, until stdin closes.
ECHO = (
    "import sys\n"
    "print('starting up', file=sys.stderr, flush=True)\n"
    "print('', file=sys.stderr, flush=True)\n"
    "for line in sys.stdin:\n"
    "    sys.stdout.write(line)\n"
    "    sys.stdout.flush()\n"
)
# Ignores stdin closing, so closing has to kill it.
STUBBORN = "import time\nwhile True:\n    time.sleep(1)\n"


def python(script: str, cwd: Path | None = None) -> CodexLaunch:
    return CodexLaunch((sys.executable, "-I", "-c", script), {"PATH": "/usr/bin"}, cwd)


def test_the_bundled_binary_is_the_pinned_codex_executable() -> None:
    binary = bundled_binary()

    assert binary.executable.name in {"codex", "codex.exe"}
    assert binary.executable.is_file()
    assert binary.path_dir is None or binary.path_dir.is_dir()


def test_the_launch_runs_app_server_over_stdio_with_codex_home_and_helpers(
    tmp_path: Path,
) -> None:
    binary = CodexBinary(tmp_path / "bin" / "codex", tmp_path / "codex-path")

    launch = app_server_launch(
        binary,
        {"PATH": "/usr/bin", "HOME": "/Users/me", "GH_TOKEN": "secret"},
        tmp_path / "home",
        {"GH_TOKEN": ""},
        tmp_path,
    )

    assert launch.args == (str(binary.executable), "app-server", "--listen", "stdio://")
    assert launch.env["PATH"] == f"{tmp_path / 'codex-path'}:/usr/bin"
    assert launch.env[CODEX_HOME_ENV] == str(tmp_path / "home")
    assert launch.env["GH_TOKEN"] == ""
    assert launch.env["HOME"] == "/Users/me"
    assert launch.cwd == tmp_path


def test_without_a_codex_home_or_helpers_codex_uses_its_defaults(tmp_path: Path) -> None:
    launch = app_server_launch(CodexBinary(tmp_path / "codex"), {}, None)

    assert CODEX_HOME_ENV not in launch.env
    assert "PATH" not in launch.env
    assert launch.cwd is None


def test_helpers_alone_make_the_path(tmp_path: Path) -> None:
    launch = app_server_launch(CodexBinary(tmp_path / "codex", tmp_path / "helpers"), {}, None)

    assert launch.env["PATH"] == str(tmp_path / "helpers")


async def test_the_process_transport_writes_reads_and_keeps_stderr(tmp_path: Path) -> None:
    transport = await spawn(python(ECHO, tmp_path))

    await transport.write(b'{"id":1}\n')
    line = await transport.readline()
    await transport.close()

    assert line == b'{"id":1}\n'
    assert transport.stderr() == "starting up"
    assert await transport.readline() == b""


async def test_closing_kills_a_server_that_does_not_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(codex_process, "CLOSE_SECONDS", 0.2)
    transport = await spawn(python(STUBBORN))

    await transport.close()

    assert isinstance(transport, ProcessTransport)
    assert transport._process.returncode is not None  # pyright: ignore[reportPrivateUsage]
    # Closing again finds stdin closed and the process gone.
    await transport.close()


async def test_the_stderr_tail_keeps_the_last_lines_that_fit() -> None:
    lines = "".join(f"print('line {n} ' + 'x' * 80, file=sys.stderr)\n" for n in range(6))
    transport = await spawn(python(f"import sys\n{lines}"))
    await transport.readline()
    await transport.close()

    tail = transport.stderr()

    assert tail.startswith("line 3 ")
    assert tail.endswith("line 5 " + "x" * 80)
    assert len(tail) <= codex_process.STDERR_CHARS


async def test_a_single_long_stderr_line_is_cut_at_its_end() -> None:
    transport = await spawn(python("import sys\nprint('y' * 500 + 'END', file=sys.stderr)"))
    await transport.readline()
    await transport.close()

    tail = transport.stderr()

    assert tail.startswith("...")
    assert tail.endswith("END")
    assert len(tail) == codex_process.STDERR_CHARS
