"""Hands this Mac's device token to the Mac app over a private Unix socket (D075).

The socket sits in the daemon's data folder (folder 0700, socket 0600). For each
connection the daemon checks that the peer runs as its own user and not under the daemon
itself (Nest's own agents and the commands they run, B159 R02), writes the token and a
newline, and closes once the client has. It never uses what a client sends, and never
logs the token. As with `outside.sock`, this stops Nest's chats from reaching the token by
accident; it is no wall against a program that tries hard (D180).
"""

import asyncio
import contextlib
import logging
import os
import socket
import struct
import sys
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

# The Mac app looks for it in the default data folder:
# ~/Library/Application Support/nest/token.sock (`SocketTokenStore` in NestKit).
SOCKET_NAME = "token.sock"

# How to read the connecting process's credentials: (level, option, size, uid offset).
# macOS: SOL_LOCAL, LOCAL_PEERCRED fills a struct xucred {u_int cr_version; uid_t cr_uid;
# short cr_ngroups; gid_t cr_groups[16]}. Linux (the CI runs there): SOL_SOCKET,
# SO_PEERCRED fills a struct ucred {pid_t pid; uid_t uid; gid_t gid}.
_PEER_CREDENTIALS = {
    "darwin": (0, 0x001, 76, 4),
    "linux": (socket.SOL_SOCKET, 17, 12, 4),
}

# How long an answered client may keep the connection open before the daemon closes it.
CLOSE_WAIT = 1.0

type TokenSource = Callable[[], Awaitable[str]]


class PeerSocket(Protocol):
    def getsockopt(self, level: int, optname: int, buflen: int, /) -> bytes: ...


type PeerUid = Callable[[PeerSocket], int]


class TokenSocketError(Exception):
    """Another daemon is already serving the token at this path."""


def read_peer_uid(sock: PeerSocket, platform: str = sys.platform) -> int:
    """The effective uid of the process at the other end of a Unix socket."""
    try:
        level, option, size, offset = _PEER_CREDENTIALS[platform]
    except KeyError:
        raise OSError(f"peer credentials are not supported on {platform}") from None
    (uid,) = struct.unpack_from("=I", sock.getsockopt(level, option, size), offset)
    return uid


# How to read the connecting process's id: (level, option, size, pid offset). macOS:
# SOL_LOCAL, LOCAL_PEERPID gives a pid_t; Linux: the pid at the start of struct ucred.
_PEER_PID = {
    "darwin": (0, 0x002, 4, 0),
    "linux": (socket.SOL_SOCKET, 17, 12, 0),
}


def read_peer_pid(sock: PeerSocket, platform: str = sys.platform) -> int:
    """The id of the process at the other end of a Unix socket (B151)."""
    try:
        level, option, size, offset = _PEER_PID[platform]
    except KeyError:
        raise OSError(f"peer process ids are not supported on {platform}") from None
    (pid,) = struct.unpack_from("=i", sock.getsockopt(level, option, size), offset)
    return pid


type PeerPid = Callable[[PeerSocket], int]
PS_TIMEOUT_SECONDS = 3.0
# Every running process's parent: pid to parent pid.
type ProcessParents = Callable[[], Awaitable[Mapping[int, int]]]
# A process's session id.
type SessionOf = Callable[[int], int]


async def process_parents(
    ps: str = "/bin/ps", seconds: float = PS_TIMEOUT_SECONDS
) -> Mapping[int, int]:
    """Read from `ps`, which macOS and Linux both have; TimeoutError when it takes longer
    than `seconds`."""
    process = await asyncio.create_subprocess_exec(
        ps,
        "-A",
        "-o",
        "pid=,ppid=",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(seconds):
            output, _ = await process.communicate()
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    parents: dict[int, int] = {}
    for line in output.decode(errors="replace").splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0].isdigit() and fields[1].isdigit():
            parents[int(fields[0])] = int(fields[1])
    return parents


def session_of(pid: int) -> int:
    """The process's session id; its own pid when it cannot be read."""
    try:
        return os.getsid(pid)
    except OSError:
        return pid


def runs_under(pid: int, ancestor: int, parents: Mapping[int, int]) -> bool:
    """Whether `ancestor` is `pid` or one of its parents."""
    seen: set[int] = set()
    current: int | None = pid
    while current is not None and current > 1 and current not in seen:
        if current == ancestor:
            return True
        seen.add(current)
        current = parents.get(current)
    return False


def runs_under_daemon(
    pid: int, daemon_pid: int, parents: Mapping[int, int], session: SessionOf
) -> bool:
    """Runs under the daemon, or is in a session whose leader runs under the daemon or is
    gone (a terminal's or an app's session keeps its leader; an app launchd starts leads
    its own)."""
    if runs_under(pid, daemon_pid, parents):
        return True
    leader = session(pid)
    if leader == pid:
        return False
    return leader not in parents or runs_under(leader, daemon_pid, parents)


class PrivateSocket:
    """A Unix socket in a private folder that only the daemon's own user can reach: made
    0600 in a 0700 folder, a stale one cleared on start, removed on stop only if it is still
    the one it made. Subclasses answer each connection in `respond`."""

    def __init__(self, path: Path, *, what: str, close_wait: float = CLOSE_WAIT) -> None:
        """`what` names what it serves, for the log."""
        self._path = path
        self._what = what
        self._close_wait = close_wait
        self._server: asyncio.Server | None = None
        # The socket file this server made, so stop never removes another daemon's.
        self._identity: tuple[int, int] | None = None

    async def start(self) -> None:
        folder = self._path.parent
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        folder.chmod(0o700)
        await self._clear_stale()
        # The folder is private, so nobody else can reach the socket before its chmod.
        self._server = await asyncio.start_unix_server(self._answer, path=self._path)
        self._path.chmod(0o600)
        self._identity = _identity(self._path)
        logger.info("serving %s on %s", self._what, self._path)

    async def stop(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        server.close()
        await server.wait_closed()
        current = _identity(self._path)
        if current is not None and current == self._identity:
            self._path.unlink()

    async def respond(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        raise NotImplementedError

    async def _clear_stale(self) -> None:
        """Removes what a daemon that did not stop cleanly left at the path. A socket
        that still answers belongs to a running daemon and is left alone."""
        if _identity(self._path) is None:
            return
        try:
            _, writer = await asyncio.open_unix_connection(self._path)
        except OSError:
            self._path.unlink()
            return
        writer.close()
        await writer.wait_closed()
        raise TokenSocketError(f"another Nest daemon is already serving {self._path}")

    async def _answer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await self.respond(reader, writer)
        finally:
            await self._close(reader, writer)

    async def _close(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Ends the answer, then waits a moment for the client to close first. On Linux,
        closing a Unix socket with unread input resets the connection, and the client loses
        the answer; so what the client sent is read and dropped. A client that already
        left is no error."""
        try:
            writer.write_eof()
            async with asyncio.timeout(self._close_wait):
                while await reader.read(4096):
                    pass
        except (TimeoutError, OSError):
            pass
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


class TokenSocket(PrivateSocket):
    def __init__(
        self,
        path: Path,
        tokens: TokenSource,
        *,
        uid: int | None = None,
        daemon_pid: int | None = None,
        peer_uid: PeerUid = read_peer_uid,
        peer_pid: PeerPid = read_peer_pid,
        parents: ProcessParents = process_parents,
        session: SessionOf = session_of,
        close_wait: float = CLOSE_WAIT,
    ) -> None:
        """`tokens` gives the current token for each connection; `uid` is who may ask
        (default: the daemon's own user), and nothing under `daemon_pid` may (default:
        this process)."""
        super().__init__(path, what="this computer's device token", close_wait=close_wait)
        self._tokens = tokens
        self._uid = os.geteuid() if uid is None else uid
        self._daemon_pid = os.getpid() if daemon_pid is None else daemon_pid
        self._peer_uid = peer_uid
        self._peer_pid = peer_pid
        self._parents = parents
        self._session = session
        # One token read at a time: a token that needs rotating is rotated once.
        self._reading = asyncio.Lock()

    async def respond(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        sock = writer.get_extra_info("socket")
        try:
            uid = self._peer_uid(sock)
            pid = self._peer_pid(sock)
        except (OSError, struct.error):
            logger.warning("refused a token request: could not read the peer's credentials")
            return
        if uid != self._uid:
            logger.warning("refused a token request from uid %d", uid)
            return
        try:
            parents = await self._parents()
        except (OSError, TimeoutError):
            logger.warning("refused a token request: could not list the running processes")
            return
        if pid not in parents:
            # Gone already, so its session cannot be checked; a child it forked may read.
            logger.warning("refused a token request from process %d, which has exited", pid)
            return
        # Unlike outside.sock, a process left to launchd may ask: the Mac app is one.
        if runs_under_daemon(pid, self._daemon_pid, parents, self._session):
            logger.warning("refused a token request from process %d, inside Nest", pid)
            return
        async with self._reading:
            try:
                token = await self._tokens()
            except Exception:
                logger.exception("could not read the device token for a token request")
                return
        writer.write(token.encode() + b"\n")
        await writer.drain()


def _identity(path: Path) -> tuple[int, int] | None:
    """The file's device and inode, without following a link; None when nothing is there."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    return info.st_dev, info.st_ino
