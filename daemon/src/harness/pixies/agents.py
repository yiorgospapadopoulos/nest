"""The pixies a project chat can call with `@slug`, as Claude Code subagents, and the
teams it can call with `@handle` (B40); in a pixie's own chat, every other pixie (B41).
"""

from dataclasses import dataclass

from harness.pixies.errors import PixieNotFoundError
from harness.pixies.files import PixieFiles
from harness.pixies.models import Pixie, PixieTeam
from harness.pixies.prompt import call_prompt
from harness.pixies.store import PixieStore
from harness.pixies.team_store import TeamStore
from harness.providers.base import Subagent
from harness.sessions.models import Session
from harness.sessions.subagents import ChatAgents, TeamCall

# The engine's model list names Claude Code's default model this way.
DEFAULT_MODEL = "default"
# What a pixie with read access never gets in a project.
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
# Names the members too: told only the leader, the chat looked for a team it could not see.
TEAM_CALL = (
    "\n\n(The user called the team @{handle}, a team of pixies set up in harness. Its"
    " members are these subagents: {members}. First use the subagent {leader} to plan which"
    " member does which part. Then call each member as the plan says. Then sum up the"
    " results.)"
)
TEAM_SECTION = """## Your team
You lead the team {name} (@{handle}). Its members in this chat:
{members}
When you are asked to plan a request for the team, reply only with a short plan that \
names the members by slug (you may name yourself) and says what each one does. Do none \
of the work while planning."""


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

    async def for_session(self, session: Session) -> ChatAgents:
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
        subagents = {
            item.pixie.slug: _subagent(item, _team_section(led.get(item.pixie.id), available))
            for item in available
        }
        calls = tuple(_team_call(team, available) for team in teams)
        return ChatAgents(subagents, calls)

    async def _for_pixie_chat(self, pixie_id: str) -> ChatAgents:
        subagents = {
            item.pixie.slug: _subagent(item, None)
            for pixie in await self._pixies.list_pixies()
            if pixie.id != pixie_id
            and not pixie.hidden
            and pixie.project_access != "none"
            and (item := self._read(pixie)) is not None
        }
        return ChatAgents(subagents)

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


def _team_call(team: PixieTeam, available: list[_Available]) -> TeamCall:
    """The instruction a message calling the team gets: its offered members in pixie
    order, the leader marked, and the steps.
    """
    members = [item.pixie for item in available if item.pixie.team_id == team.id]
    # Offered teams have an offered leader.
    leader = next(item.pixie.slug for item in available if item.pixie.id == team.leader_id)
    names = ", ".join(
        f"{pixie.slug} (leader)" if pixie.id == team.leader_id else pixie.slug for pixie in members
    )
    return TeamCall(team.handle, TEAM_CALL.format(handle=team.handle, members=names, leader=leader))


def _team_section(team: PixieTeam | None, available: list[_Available]) -> str | None:
    if team is None:
        return None
    members = "\n".join(
        f"- {item.pixie.slug}: {item.description}"
        for item in available
        if item.pixie.team_id == team.id
    )
    return TEAM_SECTION.format(name=team.name, handle=team.handle, members=members)


def _model(model: str | None) -> str | None:
    """Claude Code's default model is no name a subagent takes: it inherits the chat's."""
    return None if model is None or model.lower() == DEFAULT_MODEL else model


def _subagent(item: _Available, team: str | None) -> Subagent:
    pixie = item.pixie
    denied = tuple(pixie.disallowed_tools)
    if pixie.project_access == "read":
        denied += EDIT_TOOLS
    return Subagent(
        description=item.description,
        prompt=call_prompt(pixie, item.soul, item.memory, team),
        permission_mode=pixie.permission_mode,
        model=_model(pixie.model),
        effort=pixie.effort,
        skills=tuple(pixie.skills),
        disallowed_tools=denied,
    )
