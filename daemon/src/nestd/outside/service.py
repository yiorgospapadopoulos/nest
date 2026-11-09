"""What outside clients may do in Nest, and switching them on and off (B151, D180).

Every call re-reads the client's level, so lowering it applies at once. Pixie chats, habit
runs and called pixies are never touched; approvals stay the user's to answer in Nest.
"""

import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta, tzinfo

from pydantic import JsonValue

from nestd import __version__
from nestd.approvals.models import Approval, ApprovalKind, ApprovalStatus
from nestd.approvals.queue import ApprovalQueue
from nestd.clock import Clock
from nestd.errors import NestError, NotFoundError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.outside.config import McpConfig
from nestd.outside.models import (
    ACCESS,
    ACCESS_LABELS,
    CLIENT_KINDS,
    LABELS,
    MAX_PER_DAY,
    MAX_RUNNING,
    Access,
    Chat,
    ChatDetails,
    ClientKind,
    OutsideClient,
    PixieEntry,
    Project,
    StartChat,
    Status,
    Transcript,
    client_kind,
)
from nestd.outside.store import ClientRow, ClientStore
from nestd.outside.tokens import ClientTokens
from nestd.pixies import digest
from nestd.pixies.service import PixieService
from nestd.pixies.teams import TeamService
from nestd.repos.service import RepoService
from nestd.sessions.manager import SessionManager
from nestd.sessions.models import IN_FLIGHT, CreateSession, Sender, Session, SessionMode
from nestd.sessions.store import SessionStore
from nestd.sessions.subagents import mention

TRANSCRIPT_LIMIT = 40
TRANSCRIPT_MAX = 200
TRANSCRIPT_PAGE = 1000
LAST_EVENTS = 1000
_NEWEST = 2**62
# How often a client's "last used" is written, at most.
SEEN_EVERY = timedelta(minutes=1)


class OutsideRefusedError(NestError):
    """The client's level is too low, or it asked for something no client may do."""

    status_code = 403

    def __init__(self, message: str, needs: Access | None = None) -> None:
        super().__init__(message)
        self.needs = needs

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "needs": self.needs}


class OutsideService:
    def __init__(
        self,
        *,
        store: ClientStore,
        tokens: ClientTokens,
        config: McpConfig,
        sessions: SessionManager,
        session_store: SessionStore,
        approvals: ApprovalQueue,
        bus: EventBus,
        repos: RepoService,
        pixies: PixieService,
        teams: TeamService,
        clock: Clock,
        zone: tzinfo | None,
    ) -> None:
        """`zone` decides when a day's start limit resets; None is the system's zone."""
        self.config = config
        self._store = store
        self._tokens = tokens
        self._sessions = sessions
        self._session_store = session_store
        self._approvals = approvals
        self._bus = bus
        self._repos = repos
        self._pixies = pixies
        self._teams = teams
        self._clock = clock
        self._zone = zone
        # One start at a time per client, so parallel calls cannot pass a limit together.
        self._start_locks: dict[ClientKind, asyncio.Lock] = {}
        self._changing = asyncio.Lock()

    # Settings

    async def clients(self) -> list[OutsideClient]:
        rows = {row.kind: row for row in await self._store.list_on()}
        return [self._view(kind, rows.get(kind)) for kind in CLIENT_KINDS]

    async def turn_on(self, kind: ClientKind, access: Access) -> OutsideClient:
        """Switches the client on at `access`, or changes its level. Claude Code and Codex
        get Nest's MCP server in their config when switched on; if that fails, it stays off.
        """
        async with self._changing:
            if await self._store.get(kind) is None:
                await self.config.add(kind)
            await self._store.turn_on(kind, access)
        return await self._changed(kind)

    async def turn_off(self, kind: ClientKind) -> OutsideClient:
        """Its tokens stop working at once, then Nest's server leaves its config."""
        async with self._changing:
            self._tokens.drop(kind)
            await self._store.turn_off(kind)
            try:
                await self.config.remove(kind)
            finally:
                await self._changed(kind)
        return self._view(kind, None)

    # Tokens

    async def issue_token(self, kind: ClientKind) -> str | None:
        """A fresh token for a client that is on; None when it is off. Waits for a switch
        in progress, so no token outlives switching the client off."""
        async with self._changing:
            if await self._store.get(kind) is None:
                return None
            return self._tokens.issue(kind)

    async def authenticate(self, token: str) -> ClientRow | None:
        kind = self._tokens.kind_of(token)
        row = None if kind is None else await self._store.get(kind)
        if row is None:
            return None
        now = self._clock.now()
        if row.last_seen_at is None or now - row.last_seen_at >= SEEN_EVERY:
            await self._store.seen(row.kind)
        return row

    # Read

    async def status(self, client: ClientRow) -> Status:
        sessions = await self._sessions.list_sessions()
        pending = await self._pending()
        return Status(
            version=__version__,
            client=client.kind,
            access=client.access,
            running=sum(1 for session in sessions if session.state in IN_FLIGHT),
            waiting=sum(1 for session in sessions if session.id in pending),
        )

    def projects(self) -> list[Project]:
        return [
            Project(name=repo.name, path=str(repo.path), git=repo.git)
            for repo in self._repos.list_repos()
        ]

    async def chats(self, project: str | None, state: str | None) -> list[Chat]:
        pending = await self._pending()
        return [
            self._chat(session, pending.get(session.id, []))
            for session in await self._sessions.list_sessions(project)
            if state is None or session.state.value == state
        ]

    async def chat(self, session_id: str) -> ChatDetails:
        session = await self._session(session_id)
        pending = (await self._pending()).get(session.id, [])
        return ChatDetails(
            **self._chat(session, pending).model_dump(),
            last_answer=await self._last_answer(session.id),
            last_error=session.last_error,
        )

    async def transcript(self, session_id: str, since: int | None, limit: int | None) -> Transcript:
        session = await self._session(session_id)
        count = max(1, min(limit or TRANSCRIPT_LIMIT, TRANSCRIPT_MAX))
        if since is None:
            events = await self._bus.session_events(session.id, 0, _NEWEST, TRANSCRIPT_PAGE)
            shown = digest.entries(events)[-count:]
            return Transcript(text=digest.transcript(session, shown, None), more=None)
        events = await self._bus.session_events(session.id, since, None, TRANSCRIPT_PAGE)
        shown, more = digest.page(digest.entries(events), count)
        if more is None and len(events) == TRANSCRIPT_PAGE:
            more = events[-1].id
        return Transcript(text=digest.transcript(session, shown, None), more=more)

    async def pixies(self) -> list[PixieEntry]:
        teams = [
            PixieEntry(handle=team.handle, name=team.name, kind="team")
            for team in await self._teams.list_teams()
        ]
        pixies = [
            PixieEntry(handle=pixie.slug, name=pixie.name, kind="pixie")
            for pixie in await self._pixies.list_pixies()
            if not pixie.hidden
        ]
        return pixies + teams

    # Message

    async def send(self, client: ClientRow, session_id: str, text: str) -> ChatDetails:
        require(client, "message", "send a message")
        session = await self._session(session_id)
        await self._check_calls(client, text)
        await self._sessions.send(
            session.id, text, [], sender=Sender(extra={"from_client": client.kind})
        )
        return await self.chat(session.id)

    # Full

    async def start(self, client: ClientRow, request: StartChat) -> ChatDetails:
        require(client, "full", "start a chat")
        mode: SessionMode | None = (
            None if request.worktree is None else "worktree" if request.worktree else "in_place"
        )
        create = CreateSession(
            repo=request.project,
            prompt=request.prompt,
            mode=mode,
            model=request.model,
            effort=request.effort,
            permission_mode=request.permission_mode,
            provider=request.engine,
        )
        await self._check_calls(client, request.prompt)
        async with self._start_locks.setdefault(client.kind, asyncio.Lock()):
            await self._require_room(client.kind)
            session = await self._sessions.create(create, started_by_client=client.kind)
        return await self.chat(session.id)

    async def call(self, client: ClientRow, project: str, handle: str, task: str) -> ChatDetails:
        """A new chat whose first message calls the pixie or team, as `@handle` does."""
        require(client, "full", "call a pixie")
        known = {entry.handle for entry in await self.pixies()}
        name = handle.removeprefix("@")
        if name not in known:
            msg = f"No pixie or team is called @{name}. List them with list_pixies."
            raise NotFoundError(msg)
        return await self.start(client, StartChat(project=project, prompt=f"@{name} {task}"))

    # Inside

    def _view(self, kind: ClientKind, row: ClientRow | None) -> OutsideClient:
        return OutsideClient(
            kind=kind,
            label=LABELS[kind],
            on=row is not None,
            access=None if row is None else row.access,
            turned_on_at=None if row is None else row.turned_on_at,
            last_seen_at=None if row is None else row.last_seen_at,
            command=self.config.command(kind),
        )

    async def _changed(self, kind: ClientKind) -> OutsideClient:
        view = self._view(kind, await self._store.get(kind))
        await self._bus.publish(
            types.OUTSIDE_CLIENT_CHANGED, {"client": view.model_dump(mode="json")}
        )
        return view

    async def _check_calls(self, client: ClientRow, text: str) -> None:
        """A message that calls a pixie or team (`@handle`) needs Full access, as calling
        one does; a hidden pixie is the user's alone to call."""
        handles = [(pixie.slug, pixie.hidden) for pixie in await self._pixies.list_pixies()]
        handles += [(team.handle, False) for team in await self._teams.list_teams()]
        for handle, hidden in handles:
            if not mention(handle).search(text):
                continue
            if hidden:
                msg = f"@{handle} is a hidden pixie; only the user calls it, in Nest."
                raise OutsideRefusedError(msg)
            require(client, "full", "call a pixie")

    async def _session(self, session_id: str) -> Session:
        session = await self._sessions.get(session_id)
        if session.pixie_id is not None:
            raise OutsideRefusedError("That is a pixie's chat; outside clients never act on them.")
        return session

    async def _pending(self) -> dict[str, list[ApprovalKind]]:
        pending: dict[str, list[ApprovalKind]] = {}
        approvals: Sequence[Approval] = await self._approvals.list_approvals(ApprovalStatus.PENDING)
        for approval in approvals:
            pending.setdefault(approval.session_id, []).append(approval.kind)
        return pending

    def _chat(self, session: Session, pending: list[ApprovalKind]) -> Chat:
        return Chat(
            id=session.id,
            title=session.title,
            project=session.repo,
            state=session.state.value,
            status=digest.status(session, pending),
            waiting_on=[kind.value for kind in pending],
            engine=session.provider,
            model=session.model,
            permission_mode=session.permission_mode,
            worktree=session.mode == "worktree",
            branch=session.branch,
            pr_url=session.pr_url,
            started_by=_starter(session),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    async def _last_answer(self, session_id: str) -> str | None:
        events = await self._bus.session_events(session_id, 0, _NEWEST, LAST_EVENTS)
        for event in reversed(events):
            payload = event.payload
            if event.type != types.SESSION_MESSAGE or payload.get("parent_tool_use_id"):
                continue
            blocks = payload.get("blocks")
            texts = [
                str(block.get("text", ""))
                for block in (blocks if isinstance(blocks, list) else [])
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if texts:
                return "\n".join(texts)
        return None

    async def _require_room(self, kind: ClientKind) -> None:
        started = await self._session_store.started_by_client(kind)
        running = sum(1 for session in started if session.state in IN_FLIGHT)
        if running >= MAX_RUNNING:
            msg = (
                f"{LABELS[kind]} already has {running} chats it started running, its limit."
                " Wait until one finishes."
            )
            raise OutsideRefusedError(msg)
        midnight = _midnight(self._clock.now(), self._zone)
        today = sum(1 for session in started if session.created_at >= midnight)
        if today >= MAX_PER_DAY:
            msg = f"{LABELS[kind]} already started {today} chats today, its limit."
            raise OutsideRefusedError(msg)


def require(client: ClientRow, level: Access, action: str) -> None:
    if ACCESS.index(client.access) < ACCESS.index(level):
        msg = (
            f"To {action}, {LABELS[client.kind]} needs {ACCESS_LABELS[level]} access; it has"
            f" {ACCESS_LABELS[client.access]}. The user can change it in Nest: Settings >"
            " Terminal agents."
        )
        raise OutsideRefusedError(msg, needs=level)


def _starter(session: Session) -> str:
    if session.started_by_client is not None:
        kind = client_kind(session.started_by_client)
        return session.started_by_client if kind is None else LABELS[kind]
    if session.started_by_pixie is not None:
        return "a pixie"
    if session.started_by_trigger is not None:
        return "a GitHub trigger"
    return "the user"


def _midnight(now: datetime, zone: tzinfo | None) -> datetime:
    local = now.astimezone(zone)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)
