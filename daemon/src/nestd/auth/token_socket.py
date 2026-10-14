"""Hands this Mac's device token to the Mac app over a private Unix socket (D075).

The socket sits in the daemon's data folder (folder 0700, socket 0600). For each
connection the daemon checks that the peer runs as its own user, writes the token and a
newline, and closes. It never reads what a client sends, and never logs the token.
"""

import asyncio
import logging
import os
import socket
import struct
import sys
from collections.abc import Awaitable, Callable
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


class TokenSocket:
    def __init__(
        self,
        path: Path,
        tokens: TokenSource,
        *,
        uid: int | None = None,
        peer_uid: PeerUid = read_peer_uid,
    ) -> None:
        """`tokens` gives the current token for each connection; `uid` is who may ask
        (default: the daemon's own user)."""
        self._path = path
        self._tokens = tokens
        self._uid = os.geteuid() if uid is None else uid
        self._peer_uid = peer_uid
        self._server: asyncio.Server | None = None
        # The socket file this server made, so stop never removes another daemon's.
        self._identity: tuple[int, int] | None = None
        # One token read at a time: a token that needs rotating is rotated once.
        self._reading = asyncio.Lock()

    async def start(self) -> None:
        folder = self._path.parent
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        folder.chmod(0o700)
        await self._clear_stale()
        # The folder is private, so nobody else can reach the socket before its chmod.
        self._server = await asyncio.start_unix_server(self._answer, path=self._path)
        self._path.chmod(0o600)
        self._identity = _identity(self._path)
        logger.info("serving this Mac's device token on %s", self._path)

    async def stop(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        server.close()
        await server.wait_closed()
        current = _identity(self._path)
        if current is not None and current == self._identity:
            self._path.unlink()

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

    async def _answer(self, _reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await self._send_token(writer)
        finally:
            writer.close()
            await writer.wait_closed()

    async def _send_token(self, writer: asyncio.StreamWriter) -> None:
        try:
            uid = self._peer_uid(writer.get_extra_info("socket"))
        except (OSError, struct.error):
            logger.warning("refused a token request: could not read the peer's credentials")
            return
        if uid != self._uid:
            logger.warning("refused a token request from uid %d", uid)
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
