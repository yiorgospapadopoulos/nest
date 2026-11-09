"""Hands outside clients their tokens over a private Unix socket (B151, D180).

A client writes one line, its kind, such as `claude_code`. The daemon checks that the
peer runs as its own user and not under the daemon itself (Nest's own agents and the
commands they run), and that the client is switched on, then answers one JSON line with a
fresh token. The socket, `outside.sock`, sits beside the Mac app's in the data folder.
"""

import asyncio
import logging
import os
import struct
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from nestd.auth.token_socket import (
    PeerSocket,
    PeerUid,
    PrivateSocket,
    read_peer_pid,
    read_peer_uid,
)
from nestd.outside.models import ClientKind, TokenAnswer, client_kind

logger = logging.getLogger(__name__)

# A kind is a short word; a client that sends more, or nothing for this long, gets nothing.
REQUEST_MAX = 64
REQUEST_SECONDS = 2.0

type PeerPid = Callable[[PeerSocket], int]
# Every running process's parent: pid to parent pid.
type ProcessParents = Callable[[], Awaitable[Mapping[int, int]]]
# The token for a kind that is on, or None when it is off.
type IssueToken = Callable[[ClientKind], Awaitable[str | None]]


async def process_parents() -> Mapping[int, int]:
    """Read from `ps`, which macOS and Linux both have."""
    process = await asyncio.create_subprocess_exec(
        "/bin/ps",
        "-A",
        "-o",
        "pid=,ppid=",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    output, _ = await process.communicate()
    parents: dict[int, int] = {}
    for line in output.decode(errors="replace").splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0].isdigit() and fields[1].isdigit():
            parents[int(fields[0])] = int(fields[1])
    return parents


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


class ClientSocket(PrivateSocket):
    def __init__(
        self,
        path: Path,
        issue: IssueToken,
        *,
        uid: int | None = None,
        daemon_pid: int | None = None,
        peer_uid: PeerUid = read_peer_uid,
        peer_pid: PeerPid = read_peer_pid,
        parents: ProcessParents = process_parents,
    ) -> None:
        super().__init__(path, what="outside clients' tokens")
        self._issue = issue
        self._uid = os.geteuid() if uid is None else uid
        self._daemon_pid = os.getpid() if daemon_pid is None else daemon_pid
        self._peer_uid = peer_uid
        self._peer_pid = peer_pid
        self._parents = parents

    async def respond(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        sock = writer.get_extra_info("socket")
        try:
            uid = self._peer_uid(sock)
            pid = self._peer_pid(sock)
        except (OSError, struct.error):
            logger.warning("refused a client token request: could not read the peer")
            return
        if uid != self._uid:
            logger.warning("refused a client token request from uid %d", uid)
            return
        try:
            async with asyncio.timeout(REQUEST_SECONDS):
                line = await reader.readline()
        except TimeoutError:
            return
        answer = await self._answer_for(line, pid)
        writer.write(answer.model_dump_json(exclude_none=True).encode() + b"\n")
        await writer.drain()

    async def _answer_for(self, line: bytes, pid: int) -> TokenAnswer:
        kind = client_kind(line.decode(errors="replace").strip())
        if len(line) > REQUEST_MAX or kind is None:
            return TokenAnswer(error="unknown_client")
        if runs_under(pid, self._daemon_pid, await self._parents()):
            # Nest's own chats have their Nest tools and limits; this would reach past them.
            return TokenAnswer(error="inside_nest")
        token = await self._issue(kind)
        return TokenAnswer(error="off") if token is None else TokenAnswer(token=token)
