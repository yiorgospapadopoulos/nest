"""The `nest` command's chat commands (B151): list, show, start and message Nest's chats,
call pixies and open a chat in the app, from a terminal. `--json` prints what Nest
answered; `--wait` waits until the chat stops working.

Exit codes: 0 done, 1 failed, stopped or refused, 2 the chat waits on the user in Nest, 3
the chat was still working when `--wait` ran out.
"""

import argparse
import asyncio
import math
import subprocess
import sys
from collections.abc import Callable, Sequence
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

from nestd.outside.client import BUSY, NestApiError, NestClient, NestUnavailableError
from nestd.outside.models import Chat, ChatDetails, ClientKind, StartChat, StartMode
from nestd.outside.text import (
    SHORT_ID,
    chat_details,
    chat_lines,
    pixie_lines,
    project_lines,
    status_text,
)

CHAT_COMMANDS = ("status", "projects", "list", "show", "new", "send", "open", "pixies", "call")
MCP_CLIENTS: tuple[ClientKind, ...] = ("claude_code", "codex", "other")
MODES: dict[str, StartMode] = {"plan": "plan", "ask": "default", "accept-edits": "acceptEdits"}
WAIT_MINUTES = 30
STATES = ["starting", "running", "waiting", "idle", "failed", "interrupted", "closed"]

type AddParser = Callable[..., argparse.ArgumentParser]


def add_commands(add: AddParser) -> None:
    """Adds the chat commands and `mcp` to the `nest` command's parser."""
    _json(add("status", help="say whether Nest runs and what waits on you"))
    _json(add("projects", help="list the projects"))
    listing = _json(add("list", help="list the chats"))
    listing.add_argument("--project", help="only this project's chats")
    listing.add_argument("--state", choices=STATES, help="only chats in this state")
    show = _waits(_json(add("show", help="show a chat and its last answer")))
    show.add_argument("chat", help="the chat's id, or the start of it")
    new = _waits(_json(add("new", help="start a chat")))
    new.add_argument("task", help="what the chat should do")
    new.add_argument("--project", required=True, help="the project to work in")
    place = new.add_mutually_exclusive_group()
    place.add_argument("--worktree", action="store_true", help="work in a new worktree")
    place.add_argument("--in-place", action="store_true", help="work in the project's folder")
    new.add_argument("--engine", help="the engine, such as claude or codex")
    new.add_argument("--model", help="the model; the engine's default when left out")
    new.add_argument("--effort", help="thinking effort, such as low, medium or high")
    new.add_argument("--mode", choices=list(MODES), default="ask", help="permission mode")
    send = _waits(_json(add("send", help="send a message to a chat")))
    send.add_argument("chat", help="the chat's id, or the start of it")
    send.add_argument("message", help="the message")
    opened = add("open", help="open a chat in Nest")
    opened.add_argument("chat", help="the chat's id, or the start of it")
    _json(add("pixies", help="list the pixies and teams you can call"))
    call = _waits(_json(add("call", help="call a pixie or team in a new chat")))
    call.add_argument("pixie", help="the pixie's or team's handle, such as reviewer")
    call.add_argument("task", help="what it should do")
    call.add_argument("--project", required=True, help="the project to work in")
    mcp = add("mcp", help="serve Nest's tools to an AI app over standard input and output")
    mcp.add_argument("--client", required=True, choices=list(MCP_CLIENTS))


def run(args: argparse.Namespace, client: NestClient | None = None) -> int:
    """Runs a chat command, or `mcp`; `client` replaces the daemon in tests."""
    if args.command == "mcp":
        from nestd.outside.mcp_server import serve

        asyncio.run(serve(client or NestClient(args.client)))
        return 0
    try:
        return asyncio.run(execute(args, client or NestClient("shell")))
    except (NestUnavailableError, NestApiError) as error:
        print(f"nest: {error}", file=sys.stderr)
        return 1
    except ValidationError as error:
        print(f"nest: {problem(error)}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # A chat being waited on keeps going.
        return 130


def problem(error: ValidationError) -> str:
    """The first problem in plain words, as `field: message`."""
    first = error.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"{where}: {first['msg']}" if where else first["msg"]


async def execute(args: argparse.Namespace, nest: NestClient) -> int:
    """A chat command's work; errors are the caller's to print."""
    command: str = args.command
    if command == "status":
        status = await nest.status()
        return _out(args, status, status_text(status))
    if command == "projects":
        projects = await nest.projects()
        return _out(args, projects, project_lines(projects))
    if command == "list":
        chats = await nest.chats(args.project, args.state)
        return _out(args, chats, chat_lines(chats))
    if command == "pixies":
        pixies = await nest.pixies()
        return _out(args, pixies, pixie_lines(pixies))
    if command == "open":
        return _open(nest, await nest.chat(await nest.resolve(args.chat)))
    if command == "show":
        chat = await nest.chat(await nest.resolve(args.chat))
    elif command == "send":
        chat = await nest.send(await nest.resolve(args.chat), args.message)
    elif command == "call":
        chat = await nest.call(args.pixie, args.project, args.task)
    else:
        chat = await nest.start(_start(args))
    if args.wait:
        chat = await nest.wait(chat, args.timeout * 60, fresh=command != "show")
        return _out(args, chat, chat_details(chat), _exit(chat))
    if command == "show":
        return _out(args, chat, chat_details(chat), _exit(chat))
    short = chat.id[:SHORT_ID]
    text = (
        f'{"Sent to" if command == "send" else "Started"} chat {short} "{chat.title}" in'
        f" {chat.project}: {chat.status}. Follow it with `nest show {short} --wait`, or open"
        f" it with `nest open {short}`."
    )
    return _out(args, chat, text)


def _start(args: argparse.Namespace) -> StartChat:
    worktree = True if args.worktree else False if args.in_place else None
    return StartChat(
        project=args.project,
        prompt=args.task,
        worktree=worktree,
        engine=args.engine,
        model=args.model,
        effort=args.effort,
        permission_mode=MODES[args.mode],
    )


def _open(nest: NestClient, chat: ChatDetails) -> int:
    web = f"{nest.base_url}/chat/{chat.id}"
    if sys.platform == "darwin":
        link = f"nest://chat/{chat.id}?project={quote(chat.project)}"
        if launch(["/usr/bin/open", link]) or launch(["/usr/bin/open", web]):
            print(f'Opened chat {chat.id[:SHORT_ID]} "{chat.title}".')
            return 0
    elif launch(["xdg-open", web]):
        print(f'Opened chat {chat.id[:SHORT_ID]} "{chat.title}" in the browser.')
        return 0
    print(f"nest: could not open it; it is at {web}", file=sys.stderr)
    return 1


def launch(argv: Sequence[str]) -> bool:
    """Runs an opener such as xdg-open. Its output goes nowhere: a browser it starts keeps
    what it was given open, and a pipe it held would keep this waiting until the time
    limit, as if the opener had failed."""
    try:
        done = subprocess.run(  # noqa: S603
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def _exit(chat: Chat) -> int:
    if chat.state in BUSY:
        return 3
    if chat.state in ("failed", "interrupted"):
        return 1
    return 2 if chat.state == "waiting" else 0


def _out(
    args: argparse.Namespace, value: BaseModel | Sequence[BaseModel], text: str, code: int = 0
) -> int:
    if args.json:
        if not isinstance(value, BaseModel):
            print("[" + ",".join(item.model_dump_json() for item in value) + "]")
        else:
            print(value.model_dump_json())
    else:
        print(text)
    return code


def _json(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--json", action="store_true", help="print what Nest answered as JSON")
    return parser


def _waits(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--wait", action="store_true", help="wait until the chat stops working")
    parser.add_argument(
        "--timeout",
        type=_minutes,
        default=WAIT_MINUTES,
        help=f"minutes to wait at most (default {WAIT_MINUTES})",
    )
    return parser


def _minutes(text: str) -> float:
    try:
        minutes = float(text)
    except ValueError:
        minutes = math.nan
    if not math.isfinite(minutes) or minutes <= 0:
        msg = f"{text!r} is not a number of minutes above 0"
        raise argparse.ArgumentTypeError(msg)
    return minutes
