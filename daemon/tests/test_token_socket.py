import asyncio
import logging
import os
import shutil
import socket
import stat
import sys
import tempfile
from collections.abc import Iterator, Mapping
from functools import partial
from pathlib import Path

import pytest

from nestd.auth.token_socket import (
    CLOSE_WAIT,
    SOCKET_NAME,
    PeerSocket,
    PeerUid,
    TokenSocket,
    TokenSocketError,
    TokenSource,
    process_parents,
    read_peer_uid,
)


@pytest.fixture
def folder() -> Iterator[Path]:
    """A short folder: Unix socket paths are limited to about 104 bytes, and pytest's
    tmp_path is often longer."""
    root = Path(tempfile.mkdtemp(prefix="hx-", dir="/tmp"))
    yield root / "data"
    shutil.rmtree(root)


# The daemon's pid in these tests, and the asker's: a shell of a terminal (80), unless a
# test says otherwise.
DAEMON = 500
ASKER = 900


def serving(
    path: Path,
    source: TokenSource,
    *,
    parents: Mapping[int, int] | None = None,
    sessions: Mapping[int, int] | None = None,
    uid: int | None = None,
    peer_uid: PeerUid = read_peer_uid,
    close_wait: float = CLOSE_WAIT,
) -> TokenSocket:
    """A token socket that sees the asker as process 900 in the given process tree, as
    every test connects from this test process."""
    tree = {ASKER: 80, 80: 1} if parents is None else parents

    async def read_parents() -> Mapping[int, int]:
        return tree

    return TokenSocket(
        path,
        source,
        daemon_pid=DAEMON,
        peer_pid=lambda _: ASKER,
        parents=read_parents,
        session=lambda pid: (sessions or {}).get(pid, pid),
        uid=uid,
        peer_uid=peer_uid,
        close_wait=close_wait,
    )


def tokens(*values: str) -> tuple[list[int], TokenSource]:
    """A token source that returns `values` in turn and counts its calls."""
    calls: list[int] = []

    async def source() -> str:
        calls.append(1)
        return values[min(len(calls), len(values)) - 1]

    return calls, source


def make_folder(folder: Path, permissions: int) -> None:
    folder.mkdir()
    folder.chmod(permissions)


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def is_socket(path: Path) -> bool:
    return stat.S_ISSOCK(path.lstat().st_mode)


def exists(path: Path) -> bool:
    return path.exists()


async def ask(path: Path, send: bytes = b"") -> bytes:
    reader, writer = await asyncio.open_unix_connection(path)
    if send:
        writer.write(send)
    data = await reader.read()
    writer.close()
    await writer.wait_closed()
    return data


async def test_answers_with_the_token_and_a_newline(folder: Path) -> None:
    _, source = tokens("tok-1")
    server = serving(folder / SOCKET_NAME, source)
    await server.start()
    try:
        assert await ask(folder / SOCKET_NAME) == b"tok-1\n"
        # What a client sends is never read: the answer is the same.
        assert await ask(folder / SOCKET_NAME, b"GET / HTTP/1.1\r\n\r\n") == b"tok-1\n"
    finally:
        await server.stop()


async def test_a_client_that_never_closes_is_closed_after_a_short_wait(folder: Path) -> None:
    _, source = tokens("tok-1")
    server = serving(folder / SOCKET_NAME, source, close_wait=0.05)
    await server.start()
    reader, writer = await asyncio.open_unix_connection(folder / SOCKET_NAME)
    try:
        assert await reader.read() == b"tok-1\n"
        # Stopping waits for open connections, so it only returns once the server closed this one.
        await asyncio.wait_for(server.stop(), 2)
    finally:
        writer.close()
        await writer.wait_closed()


async def test_each_connection_asks_for_the_current_token(folder: Path) -> None:
    calls, source = tokens("first", "rotated")
    server = serving(folder / SOCKET_NAME, source)
    await server.start()
    try:
        assert await ask(folder / SOCKET_NAME) == b"first\n"
        assert await ask(folder / SOCKET_NAME) == b"rotated\n"
        assert len(calls) == 2
    finally:
        await server.stop()


async def test_only_the_owner_can_reach_the_socket(folder: Path) -> None:
    make_folder(folder, 0o755)
    _, source = tokens("tok")
    server = serving(folder / SOCKET_NAME, source)
    await server.start()
    try:
        assert mode(folder) == 0o700
        assert is_socket(folder / SOCKET_NAME)
        assert mode(folder / SOCKET_NAME) == 0o600
    finally:
        await server.stop()


async def test_creates_a_missing_folder_private(folder: Path) -> None:
    _, source = tokens("tok")
    server = serving(folder / "nested" / SOCKET_NAME, source)
    await server.start()
    try:
        assert mode(folder / "nested") == 0o700
    finally:
        await server.stop()


async def test_refuses_a_peer_running_as_another_user(
    folder: Path, caplog: pytest.LogCaptureFixture
) -> None:
    calls, source = tokens("secret-token")
    server = serving(
        folder / SOCKET_NAME, source, uid=os.geteuid(), peer_uid=lambda _: os.geteuid() + 1
    )
    await server.start()
    try:
        with caplog.at_level(logging.WARNING, logger="nestd.auth.token_socket"):
            assert await ask(folder / SOCKET_NAME) == b""
    finally:
        await server.stop()
    assert calls == []
    assert f"uid {os.geteuid() + 1}" in caplog.text
    assert "secret-token" not in caplog.text


async def test_a_child_of_the_daemon_gets_no_token(folder: Path) -> None:
    """Nest's own agents and their commands run under the daemon (B159 R02)."""
    calls, source = tokens("secret-token")
    server = TokenSocket(folder / SOCKET_NAME, source)
    await server.start()
    reader = (
        "import socket, sys\n"
        "s = socket.socket(socket.AF_UNIX)\n"
        "s.connect(sys.argv[1])\n"
        "print(repr(s.recv(4096)))\n"
    )
    try:
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-c",
            reader,
            str(folder / SOCKET_NAME),
            stdout=asyncio.subprocess.PIPE,
        )
        output, _ = await asyncio.wait_for(child.communicate(), 10)
    finally:
        await server.stop()
    assert output.strip() == b"b''"
    assert calls == []


async def test_a_process_in_an_agents_session_gets_no_token(folder: Path) -> None:
    # Its parent is gone, but its session began with an agent's command (700).
    calls, source = tokens("secret-token")
    tree = {ASKER: 650, 650: 1, 700: DAEMON, DAEMON: 1}
    server = serving(folder / SOCKET_NAME, source, parents=tree, sessions={ASKER: 700})
    await server.start()
    try:
        assert await ask(folder / SOCKET_NAME) == b""
    finally:
        await server.stop()
    assert calls == []


async def test_a_caller_that_already_exited_gets_no_token(folder: Path) -> None:
    """Its session cannot be checked, and a child it forked could read the answer."""
    calls, source = tokens("secret-token")
    tree = {80: 1, 700: DAEMON, DAEMON: 1}
    server = serving(folder / SOCKET_NAME, source, parents=tree)
    await server.start()
    try:
        assert await ask(folder / SOCKET_NAME) == b""
    finally:
        await server.stop()
    assert calls == []


async def test_no_token_when_listing_the_processes_hangs(
    folder: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """B159 recheck 2: each request waited on `ps` with no time limit."""
    slow_ps = folder.parent / "ps"
    slow_ps.write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
    slow_ps.chmod(0o700)
    async with asyncio.timeout(5):
        with pytest.raises(TimeoutError):
            await process_parents(ps=str(slow_ps), seconds=0.2)
    calls, source = tokens("secret-token")
    server = TokenSocket(
        folder / SOCKET_NAME,
        source,
        daemon_pid=DAEMON,
        peer_pid=lambda _: ASKER,
        parents=partial(process_parents, ps=str(slow_ps), seconds=0.2),
    )
    await server.start()
    try:
        async with asyncio.timeout(5):
            assert await ask(folder / SOCKET_NAME) == b""
    finally:
        await server.stop()
    assert calls == []
    assert "could not list the running processes" in caplog.text


async def test_an_app_launchd_started_gets_the_token(folder: Path) -> None:
    """The Mac app's parent is launchd and it leads its own session."""
    _, source = tokens("tok")
    server = serving(folder / SOCKET_NAME, source, parents={ASKER: 1})
    await server.start()
    try:
        assert await ask(folder / SOCKET_NAME) == b"tok\n"
    finally:
        await server.stop()


async def test_refuses_a_peer_whose_credentials_cannot_be_read(
    folder: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def unreadable(_: PeerSocket) -> int:
        raise OSError("no credentials")

    calls, source = tokens("secret-token")
    server = serving(folder / SOCKET_NAME, source, peer_uid=unreadable)
    await server.start()
    try:
        with caplog.at_level(logging.WARNING, logger="nestd.auth.token_socket"):
            assert await ask(folder / SOCKET_NAME) == b""
    finally:
        await server.stop()
    assert calls == []
    assert "could not read" in caplog.text


async def test_a_failing_token_source_closes_without_an_answer(
    folder: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def failing() -> str:
        raise RuntimeError("keychain locked")

    server = serving(folder / SOCKET_NAME, failing)
    await server.start()
    try:
        with caplog.at_level(logging.ERROR, logger="nestd.auth.token_socket"):
            assert await ask(folder / SOCKET_NAME) == b""
        # The server keeps serving later connections.
        assert await ask(folder / SOCKET_NAME) == b""
    finally:
        await server.stop()
    assert "could not read the device token" in caplog.text


async def test_token_reads_run_one_at_a_time(folder: Path) -> None:
    """A token that needs rotating is rotated once, not by two connections at the same time."""
    running = 0
    overlapped = False

    async def slow() -> str:
        nonlocal running, overlapped
        running += 1
        overlapped = overlapped or running > 1
        await asyncio.sleep(0.02)
        running -= 1
        return "tok"

    server = serving(folder / SOCKET_NAME, slow)
    await server.start()
    try:
        answers = await asyncio.gather(*(ask(folder / SOCKET_NAME) for _ in range(3)))
    finally:
        await server.stop()
    assert answers == [b"tok\n"] * 3
    assert not overlapped


def leave_stale_socket(path: Path) -> None:
    """A socket file nobody listens on, as a daemon that was killed leaves behind."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(path))
    stale.close()


async def test_replaces_a_stale_socket(folder: Path) -> None:
    path = folder / SOCKET_NAME
    leave_stale_socket(path)
    _, source = tokens("tok")
    server = serving(path, source)
    await server.start()
    try:
        assert await ask(path) == b"tok\n"
    finally:
        await server.stop()


async def test_replaces_a_leftover_file(folder: Path) -> None:
    path = folder / SOCKET_NAME
    make_folder(folder, 0o700)
    (folder / SOCKET_NAME).write_bytes(b"left over")
    _, source = tokens("tok")
    server = serving(path, source)
    await server.start()
    try:
        assert await ask(path) == b"tok\n"
    finally:
        await server.stop()


async def test_refuses_to_take_over_a_socket_another_daemon_serves(folder: Path) -> None:
    path = folder / SOCKET_NAME
    _, first_source = tokens("first")
    first = serving(path, first_source)
    await first.start()
    _, second_source = tokens("second")
    second = serving(path, second_source)
    try:
        with pytest.raises(TokenSocketError, match="already serving"):
            await second.start()
        assert await ask(path) == b"first\n"
        await second.stop()
        assert exists(path)
    finally:
        await first.stop()


async def test_stop_removes_the_socket(folder: Path) -> None:
    path = folder / SOCKET_NAME
    _, source = tokens("tok")
    server = serving(path, source)
    await server.start()

    await server.stop()

    assert not exists(path)
    with pytest.raises(FileNotFoundError):
        await ask(path)
    # A second stop, or one after the file went away, is harmless.
    await server.stop()


async def test_stop_tolerates_a_socket_that_is_already_gone(folder: Path) -> None:
    path = folder / SOCKET_NAME
    _, source = tokens("tok")
    server = serving(path, source)
    await server.start()
    path.unlink()

    await server.stop()

    assert not exists(path)


async def test_stop_leaves_a_socket_that_replaced_ours(folder: Path) -> None:
    path = folder / SOCKET_NAME
    _, source = tokens("tok")
    server = serving(path, source)
    await server.start()
    path.unlink()
    leave_stale_socket(path)

    await server.stop()

    assert is_socket(path)


async def test_stop_before_start_does_nothing(folder: Path) -> None:
    _, source = tokens("tok")
    await serving(folder / SOCKET_NAME, source).stop()
    assert not exists(folder)


def test_reads_the_real_peer_uid() -> None:
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with left, right:
        assert read_peer_uid(left) == os.geteuid()


def test_peer_credentials_on_an_unknown_platform_are_an_error() -> None:
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with left, right, pytest.raises(OSError, match="not supported on plan9"):
        read_peer_uid(left, platform="plan9")
