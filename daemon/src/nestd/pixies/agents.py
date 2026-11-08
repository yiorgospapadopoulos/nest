"""The pixies a project chat can call with `@slug`, as Claude Code subagents, and the
teams it can call with `@handle` (B40); in a pixie's own chat, every other pixie (B41).

A team is called through its leader, the only pixie that calls pixies: its own members
(B70). The run's call guard holds every agent to that.

A run calls the pixies on its own engine as that engine's own subagents, where the engine
has them: Claude Code's subagents, and Codex's (B112: agent roles of the thread,
`providers.codex_roles`). A pixie on another engine, and every pixie a run on an engine
without them (ACP) calls, is called with the call_pixie tool instead and runs as a session
of its own (B91): `ChatAgents.tool_calls`. A called leader's own session calls its members
the same way.
"""

from collections.abc import Callable
from dataclasses import dataclass

from nestd.computer.models import TOOL_NAMES as COMPUTER_TOOL_NAMES
from nestd.pixies.errors import PixieNotFoundError
from nestd.pixies.files import PixieFiles
from nestd.pixies.models import DEFAULT_PROVIDER, Pixie, PixieTeam
from nestd.pixies.prompt import call_prompt
from nestd.pixies.store import PixieStore
from nestd.pixies.team_store import TeamStore
from nestd.providers.base import CALL_PIXIE_TOOL, CallRules, Subagent
from nestd.providers.claude_tools import NEST_SERVER
from nestd.sessions.models import NewSession
from nestd.sessions.subagents import ChatAgents, OfferedPixie, TeamCall
from nestd.sessions.worktree_tool import WORKTREE_RULE

# The engine's model list names Claude Code's default model this way.
DEFAULT_MODEL = "default"
# What a pixie with read access never gets in a project.
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit", WORKTREE_RULE)
# Claude Code's names for the computer-use tools, which pixies get only when allowed (B150).
COMPUTER_TOOLS = tuple(f"mcp__{NEST_SERVER}__{name}" for name in COMPUTER_TOOL_NAMES)
TEAM_CALL = (
    "\n\n(The user called the team @{handle}, a team of pixies set up in Nest. Hand the"
    " whole request to its leader, {leader} and wait for"
    " its report. The leader decides which member does which part, calls them itself and"
    " puts their results together.{members} When it reports, give its report and add a"
    " short summary of what happened.)"
)
# How the leader is called: as the run's subagent, or with the call tool (B91).
LEADER_SUBAGENT = "the subagent {slug}, with the Agent tool"
# As a Codex run's own subagent (B112).
LEADER_AGENT = "the agent role {slug}, with spawn_agent (`agent_type` set to {slug}),"
LEADER_TOOL = f"the pixie {{slug}}, with the {CALL_PIXIE_TOOL} tool"
# Named, so the chat does not call them itself.
TEAM_CALL_MEMBERS = " Do not call its members ({members}) yourself."
MEMBER_NOTE = " It is called only by its team's leader, as part of a team call to @{handle}."
LEADER_NOTE = " It leads the team @{handle}: a call to the team goes to it."
TEAM_SECTION = """## Your team
You lead the team {name} (@{handle}). Its members in this chat:
{members}
When a request comes for the team, decide which member does which part; you may do a \
part yourself. Call each member with the Agent tool, with `subagent_type` set to its slug \
and `run_in_background` set to false, and wait for its result. To continue a member you \
called earlier in this conversation, use SendMessage to its agent id instead of a new \
call. Then report what each member did and the combined result. You call only your \
team's members; for other help, use Claude Code's ordinary subagents."""
# The same for a leader on Codex, whose members on Codex are its own subagents (B112).
CODEX_TEAM_SECTION = """## Your team
You lead the team {name} (@{handle}). Its members in this chat:
{members}
When a request comes for the team, decide which member does which part; you may do a \
part yourself. Call each member with spawn_agent, with `agent_type` set to its slug, and \
wait for its result. To continue a member you called earlier in this conversation, send \
it the next task (followup_task, or send_input) to its agent id instead of spawning it \
again. Then report what each member did and the combined result. You call only your \
team's members; for other help, spawn an agent without a pixie's role."""
# How a Codex run continues a pixie it called earlier in the chat, as its own subagent
# (B112), where a Claude run is told to use SendMessage (`pixies.calls.CONTINUE_NOTE`).
CODEX_CONTINUE_NOTE = (
    "\n\n(@{slug} was called earlier in this chat as agent {agent_id}. Continue that agent"
    " with followup_task (or send_input, after resume_agent if it was closed) to"
    " '{agent_id}' instead of spawning a new one.)"
)
NO_MEMBERS = "No other member is in this chat."
# A member the leader calls with the call tool, and how (B91).
TOOL_MARK = f" (call with {CALL_PIXIE_TOOL})"
TOOL_MEMBERS = (
    f" Call a member marked{TOOL_MARK} with the {CALL_PIXIE_TOOL} tool instead, with `pixie`"
    " set to its slug, and wait for its report."
)

CODEX = "codex"
# The engines, by provider name, that run Nest-defined subagents of their own (B112).
NATIVE_ENGINES = frozenset({DEFAULT_PROVIDER, CODEX})

# The engine, by provider name, whose own subagents run Nest-defined ones; None when it
# runs none. A pixie is the run's subagent when both name the same engine.
type InlineEngines = Callable[[str], str | None]


def native_subagents(provider: str) -> str | None:
    return provider if provider in NATIVE_ENGINES else None


@dataclass(frozen=True)
class _Available:
    pixie: Pixie
    soul: str
    memory: str

    @property
    def description(self) -> str:
        line = next((line.strip() for line in self.soul.splitlines() if line.strip()), "")
        return f"{self.pixie.name}: {line}" if line else self.pixie.name


class PixieAgents:
    def __init__(
        self,
        pixies: PixieStore,
        files: PixieFiles,
        teams: TeamStore,
        inline: InlineEngines = native_subagents,
        can_push: Callable[[], bool] = lambda: False,
        computer: Callable[[], bool] = lambda: False,
    ) -> None:
        """`inline` says which engines run Nest-defined subagents of their own; `can_push`
        whether the user lets agents push, which their prompts follow; `computer` whether
        pixies may use computer use (B150).
        """
        self._can_push = can_push
        self._computer = computer
        self._pixies = pixies
        self._files = files
        self._teams = teams
        self._inline = inline

    async def for_session(self, session: NewSession) -> ChatAgents:
        """Every pixie that may work on the chat's project: not hidden and with project
        access (every pixie works in every project, D109). A team is offered when its leader
        is, with its offered members. A pixie's own chat gets every other pixie that is
        not hidden and has project access, and no teams (B41); a called pixie's session,
        its team's members when it leads one (B91).
        """
        if session.pixie_id is not None:
            if session.called_by is not None:
                return await self._for_call(session.pixie_id, session.provider)
            return await self._for_pixie_chat(session.pixie_id, session.provider)
        available = await self._available()
        by_id = {item.pixie.id: item for item in available}
        teams = [team for team in await self._teams.list_teams() if team.leader_id in by_id]
        led = {team.leader_id: team for team in teams}
        handles = {team.id: team.handle for team in teams}
        offered = {
            item.pixie.slug: OfferedPixie(
                item.pixie.id,
                item.pixie.slug,
                item.pixie.name,
                *_offered_team(item.pixie, handles),
                leader=item.pixie.id in led,
            )
            for item in available
        }
        subagents = {
            item.pixie.slug: _subagent(
                item,
                _note(offered[item.pixie.slug]),
                self._team_section(led.get(item.pixie.id), available),
                can_push=self._can_push(),
                computer=self._computer(),
            )
            for item in available
        }
        tool_calls = self._tool_calls(session.provider, available)
        calls = tuple(_team_call(team, available, tool_calls, session.provider) for team in teams)
        rules = CallRules(
            pixies=frozenset(offered),
            main=frozenset(
                slug for slug, p in offered.items() if p.team_handle is None or p.leader
            ),
            leaders={
                item.pixie.slug: frozenset(
                    member.pixie.slug for member in _members(team, available)
                )
                for item in available
                if (team := led.get(item.pixie.id)) is not None
            },
        )
        return ChatAgents(subagents, calls, offered, rules, tool_calls)

    async def called_prompt(self, pixie: Pixie) -> str:
        """The prompt of the pixie's own session when it is called (B91): what it gets as a
        subagent, with its team section when it leads a team.
        """
        item = self._read(pixie)
        if item is None:
            msg = f"pixie {pixie.id!r} has no folder"
            raise PixieNotFoundError(msg)
        team = await self._led_team(pixie.id)
        section = self._team_section(team, await self._available()) if team else None
        return call_prompt(pixie, item.soul, item.memory, section, can_push=self._can_push())

    async def _for_pixie_chat(self, pixie_id: str, provider: str) -> ChatAgents:
        """The pixie calls every other pixie, and those it calls call none."""
        available = [item for item in await self._available() if item.pixie.id != pixie_id]
        can_push = self._can_push()
        subagents = {
            item.pixie.slug: _subagent(item, can_push=can_push, computer=self._computer())
            for item in available
        }
        everyone = frozenset(subagents)
        return ChatAgents(
            subagents,
            rules=CallRules(pixies=everyone, main=everyone),
            tool_calls=self._tool_calls(provider, available),
        )

    async def _for_call(self, pixie_id: str, provider: str) -> ChatAgents:
        """A called pixie's own session: a leader calls its team's members; any other
        pixie calls none.
        """
        team = await self._led_team(pixie_id)
        if team is None:
            return ChatAgents(rules=CallRules())
        members = _members(team, await self._available())
        slugs = frozenset(item.pixie.slug for item in members)
        return ChatAgents(
            {
                item.pixie.slug: _subagent(
                    item, can_push=self._can_push(), computer=self._computer()
                )
                for item in members
            },
            pixies={
                item.pixie.slug: OfferedPixie(
                    item.pixie.id, item.pixie.slug, item.pixie.name, team.id, team.handle
                )
                for item in members
            },
            rules=CallRules(pixies=slugs, main=slugs),
            tool_calls=self._tool_calls(provider, members),
        )

    async def _available(self) -> list["_Available"]:
        return [
            item
            for pixie in await self._pixies.list_pixies()
            if _may_work_on(pixie) and (item := self._read(pixie)) is not None
        ]

    async def _led_team(self, pixie_id: str) -> PixieTeam | None:
        teams = await self._teams.list_teams()
        return next((team for team in teams if team.leader_id == pixie_id), None)

    def _tool_calls(self, provider: str, available: list["_Available"]) -> dict[str, str]:
        """The pixies a run on `provider` calls with the call tool: all of them when its
        engine runs no Nest subagents of its own, else those on another engine.
        """
        engine = self._inline(provider)
        return {
            item.pixie.slug: item.pixie.id
            for item in available
            if engine is None or self._inline(item.pixie.provider) != engine
        }

    def _team_section(self, team: PixieTeam | None, available: list["_Available"]) -> str | None:
        """A leader's team: its members, each marked when the leader's run calls it with
        the call tool rather than as its subagent.
        """
        if team is None:
            return None
        leader = next(item.pixie for item in available if item.pixie.id == team.leader_id)
        members = _members(team, available)
        by_tool = self._tool_calls(leader.provider, members)
        lines = "\n".join(
            f"- {item.pixie.slug}{TOOL_MARK if item.pixie.slug in by_tool else ''}:"
            f" {item.description}"
            for item in members
        )
        template = CODEX_TEAM_SECTION if leader.provider == CODEX else TEAM_SECTION
        section = template.format(name=team.name, handle=team.handle, members=lines or NO_MEMBERS)
        return section + TOOL_MEMBERS if by_tool else section

    def _read(self, pixie: Pixie) -> _Available | None:
        try:
            soul = self._files.read(pixie.id, "soul").text
            memory = self._files.read(pixie.id, "memory").text
        except PixieNotFoundError:
            return None  # its folder is gone
        return _Available(pixie, soul, memory)


def _may_work_on(pixie: Pixie) -> bool:
    """Every pixie works in every project (D109), unless hidden or kept out of files."""
    return not pixie.hidden and pixie.project_access != "none"


def _offered_team(pixie: Pixie, handles: dict[str, str]) -> tuple[str | None, str | None]:
    """The pixie's team id and handle when the chat can call that team."""
    handle = None if pixie.team_id is None else handles.get(pixie.team_id)
    return (pixie.team_id, handle) if handle is not None else (None, None)


def _members(team: PixieTeam, available: list[_Available]) -> list[_Available]:
    """The team's offered pixies besides its leader, in pixie order."""
    return [
        item
        for item in available
        if item.pixie.team_id == team.id and item.pixie.id != team.leader_id
    ]


def _team_call(
    team: PixieTeam, available: list[_Available], tool_calls: dict[str, str], provider: str
) -> TeamCall:
    """The instruction a message calling the team gets: hand it to the leader, as the
    run's engine calls it.
    """
    # Offered teams have an offered leader.
    leader = next(item.pixie.slug for item in available if item.pixie.id == team.leader_id)
    slugs = ", ".join(item.pixie.slug for item in _members(team, available))
    members = TEAM_CALL_MEMBERS.format(members=slugs) if slugs else ""
    if leader in tool_calls:
        how = LEADER_TOOL.format(slug=leader)
    else:
        how = (LEADER_AGENT if provider == CODEX else LEADER_SUBAGENT).format(slug=leader)
    return TeamCall(team.handle, TEAM_CALL.format(handle=team.handle, leader=how, members=members))


def _note(pixie: OfferedPixie) -> str:
    """What its description adds: it leads its team, or only its leader calls it."""
    if pixie.team_handle is None:
        return ""
    return (LEADER_NOTE if pixie.leader else MEMBER_NOTE).format(handle=pixie.team_handle)


def _model(model: str | None) -> str | None:
    """Claude Code's default model is no name a subagent takes: it inherits the chat's."""
    return None if model is None or model.lower() == DEFAULT_MODEL else model


def _subagent(
    item: _Available, note: str = "", team: str | None = None, *, can_push: bool, computer: bool
) -> Subagent:
    """`note` ends its description; `team` is a leader's team section."""
    pixie = item.pixie
    denied = EDIT_TOOLS if pixie.project_access == "read" else ()
    if not computer:
        denied += COMPUTER_TOOLS
    return Subagent(
        description=item.description + note,
        prompt=call_prompt(pixie, item.soul, item.memory, team, can_push=can_push),
        permission_mode=pixie.permission_mode,
        model=_model(pixie.model),
        effort=pixie.effort,
        skills=tuple(pixie.skills),
        disallowed_tools=denied,
    )
