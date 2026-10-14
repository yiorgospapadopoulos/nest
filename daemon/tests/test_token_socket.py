import asyncio
import logging
import os
import shutil
import socket
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness.auth.token_socket import (
    SOCKET_NAME,
    PeerSocket,
    TokenSocket,
    TokenSocketError,
    TokenSource,
    read_peer_uid,
)


@pytest.fixture
def folder() -> Iterator[Path]:
    """A short folder: Unix socket paths are limited to about 104 bytes, and pytest's
    tmp_path is often longer."""
    root = Path(tempfile.mkdtemp(prefix="hx-", dir="/tmp"))
    yield root / "data"
    shutil.rmtree(root)


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
    server = TokenSocket(folder / SOCKET_NAME, source)
    await server.start()
    try:
        assert await ask(folder / SOCKET_NAME) == b"tok-1\n"
        # What a client sends is never read: the answer is the same.
        assert await ask(folder / SOCKET_NAME, b"GET / HTTP/1.1\r\n\r\n") == b"tok-1\n"
    finally:
        await server.stop()


async def test_each_connection_asks_for_the_current_token(folder: Path) -> None:
    calls, source = tokens("first", "rotated")
    server = TokenSocket(folder / SOCKET_NAME, source)
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
    server = TokenSocket(folder / SOCKET_NAME, source)
    await server.start()
    try:
        assert mode(folder) == 0o700
        assert is_socket(folder / SOCKET_NAME)
        assert mode(folder / SOCKET_NAME) == 0o600
    finally:
        await server.stop()


async def test_creates_a_missing_folder_private(folder: Path) -> None:
    _, source = tokens("tok")
    server = TokenSocket(folder / "nested" / SOCKET_NAME, source)
    await server.start()
    try:
        assert mode(folder / "nested") == 0o700
    finally:
        await server.stop()


async def test_refuses_a_peer_running_as_another_user(
    folder: Path, caplog: pytest.LogCaptureFixture
) -> None:
    calls, source = tokens("secret-token")
    server = TokenSocket(
        folder / SOCKET_NAME, source, uid=os.geteuid(), peer_uid=lambda _: os.geteuid() + 1
    )
    await server.start()
    try:
        with caplog.at_level(logging.WARNING, logger="harness.auth.token_socket"):
            assert await ask(folder / SOCKET_NAME) == b""
    finally:
        await server.stop()
    assert calls == []
    assert f"uid {os.geteuid() + 1}" in caplog.text
    assert "secret-token" not in caplog.text


async def test_refuses_a_peer_whose_credentials_cannot_be_read(
    folder: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def unreadable(_: PeerSocket) -> int:
        raise OSError("no credentials")

    calls, source = tokens("secret-token")
    server = TokenSocket(folder / SOCKET_NAME, source, peer_uid=unreadable)
    await server.start()
    try:
        with caplog.at_level(logging.WARNING, logger="harness.auth.token_socket"):
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

    server = TokenSocket(folder / SOCKET_NAME, failing)
    await server.start()
    try:
        with caplog.at_level(logging.ERROR, logger="harness.auth.token_socket"):
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

    server = TokenSocket(folder / SOCKET_NAME, slow)
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
    server = TokenSocket(path, source)
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
    server = TokenSocket(path, source)
    await server.start()
    try:
        assert await ask(path) == b"tok\n"
    finally:
        await server.stop()


async def test_refuses_to_take_over_a_socket_another_daemon_serves(folder: Path) -> None:
    path = folder / SOCKET_NAME
    _, first_source = tokens("first")
    first = TokenSocket(path, first_source)
    await first.start()
    _, second_source = tokens("second")
    second = TokenSocket(path, second_source)
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
    server = TokenSocket(path, source)
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
    server = TokenSocket(path, source)
    await server.start()
    path.unlink()

    await server.stop()

    assert not exists(path)


async def test_stop_leaves_a_socket_that_replaced_ours(folder: Path) -> None:
    path = folder / SOCKET_NAME
    _, source = tokens("tok")
    server = TokenSocket(path, source)
    await server.start()
    path.unlink()
    leave_stale_socket(path)

    await server.stop()

    assert is_socket(path)


async def test_stop_before_start_does_nothing(folder: Path) -> None:
    _, source = tokens("tok")
    await TokenSocket(folder / SOCKET_NAME, source).stop()
    assert not exists(folder)


def test_reads_the_real_peer_uid() -> None:
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with left, right:
        assert read_peer_uid(left) == os.geteuid()


def test_peer_credentials_on_an_unknown_platform_are_an_error() -> None:
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with left, right, pytest.raises(OSError, match="not supported on plan9"):
        read_peer_uid(left, platform="plan9")
