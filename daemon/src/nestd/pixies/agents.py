"""The pixies a project chat can call with `@slug`, as Claude Code subagents, and the
teams it can call with `@handle` (B40); in a pixie's own chat, every other pixie (B41).

A team is called through its leader, the only pixie that calls pixies: its own members
(B70). The run's call guard holds every agent to that.
"""

from dataclasses import dataclass

from nestd.pixies.errors import PixieNotFoundError
from nestd.pixies.files import PixieFiles
from nestd.pixies.models import Pixie, PixieTeam
from nestd.pixies.prompt import call_prompt
from nestd.pixies.store import PixieStore
from nestd.pixies.team_store import TeamStore
from nestd.providers.base import CallRules, Subagent
from nestd.sessions.models import NewSession
from nestd.sessions.subagents import ChatAgents, OfferedPixie, TeamCall

# The engine's model list names Claude Code's default model this way.
DEFAULT_MODEL = "default"
# What a pixie with read access never gets in a project.
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
TEAM_CALL = (
    "\n\n(The user called the team @{handle}, a team of pixies set up in Nest. Hand the"
    " whole request to its leader, the subagent {leader}, with the Agent tool and wait for"
    " its report. The leader decides which member does which part, calls them itself and"
    " puts their results together.{members} When it reports, give its report and add a"
    " short summary of what happened.)"
)
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
NO_MEMBERS = "No other member is in this chat."


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
    def __init__(self, pixies: PixieStore, files: PixieFiles, teams: TeamStore) -> None:
        self._pixies = pixies
        self._files = files
        self._teams = teams

    async def for_session(self, session: NewSession) -> ChatAgents:
        """Every pixie that may work on the chat's project: not hidden, with project
        access, and assigned to it or to every project. A team is offered when its leader
        is, with its offered members. A pixie's own chat gets every other pixie that is
        not hidden and has project access, and no teams (B41).
        """
        if session.pixie_id is not None:
            return await self._for_pixie_chat(session.pixie_id)
        available = [
            item
            for pixie in await self._pixies.list_pixies()
            if _may_work_on(pixie, session.repo) and (item := self._read(pixie)) is not None
        ]
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
                _team_section(led.get(item.pixie.id), available),
            )
            for item in available
        }
        calls = tuple(_team_call(team, available) for team in teams)
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
        return ChatAgents(subagents, calls, offered, rules)

    async def _for_pixie_chat(self, pixie_id: str) -> ChatAgents:
        """The pixie calls every other pixie, and those it calls call none."""
        subagents = {
            item.pixie.slug: _subagent(item)
            for pixie in await self._pixies.list_pixies()
            if pixie.id != pixie_id
            and not pixie.hidden
            and pixie.project_access != "none"
            and (item := self._read(pixie)) is not None
        }
        everyone = frozenset(subagents)
        return ChatAgents(subagents, rules=CallRules(pixies=everyone, main=everyone))

    def _read(self, pixie: Pixie) -> _Available | None:
        try:
            soul = self._files.read(pixie.id, "soul").text
            memory = self._files.read(pixie.id, "memory").text
        except PixieNotFoundError:
            return None  # its folder is gone
        return _Available(pixie, soul, memory)


def _may_work_on(pixie: Pixie, repo: str) -> bool:
    return (
        not pixie.hidden
        and pixie.project_access != "none"
        and (pixie.projects is None or repo in pixie.projects)
    )


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


def _team_call(team: PixieTeam, available: list[_Available]) -> TeamCall:
    """The instruction a message calling the team gets: hand it to the leader."""
    # Offered teams have an offered leader.
    leader = next(item.pixie.slug for item in available if item.pixie.id == team.leader_id)
    slugs = ", ".join(item.pixie.slug for item in _members(team, available))
    members = TEAM_CALL_MEMBERS.format(members=slugs) if slugs else ""
    return TeamCall(
        team.handle, TEAM_CALL.format(handle=team.handle, leader=leader, members=members)
    )


def _team_section(team: PixieTeam | None, available: list[_Available]) -> str | None:
    if team is None:
        return None
    members = "\n".join(
        f"- {item.pixie.slug}: {item.description}" for item in _members(team, available)
    )
    return TEAM_SECTION.format(name=team.name, handle=team.handle, members=members or NO_MEMBERS)


def _note(pixie: OfferedPixie) -> str:
    """What its description adds: it leads its team, or only its leader calls it."""
    if pixie.team_handle is None:
        return ""
    return (LEADER_NOTE if pixie.leader else MEMBER_NOTE).format(handle=pixie.team_handle)


def _model(model: str | None) -> str | None:
    """Claude Code's default model is no name a subagent takes: it inherits the chat's."""
    return None if model is None or model.lower() == DEFAULT_MODEL else model


def _subagent(item: _Available, note: str = "", team: str | None = None) -> Subagent:
    """`note` ends its description; `team` is a leader's team section."""
    pixie = item.pixie
    denied = tuple(pixie.disallowed_tools)
    if pixie.project_access == "read":
        denied += EDIT_TOOLS
    return Subagent(
        description=item.description + note,
        prompt=call_prompt(pixie, item.soul, item.memory, team),
        permission_mode=pixie.permission_mode,
        model=_model(pixie.model),
        effort=pixie.effort,
        skills=tuple(pixie.skills),
        disallowed_tools=denied,
    )
