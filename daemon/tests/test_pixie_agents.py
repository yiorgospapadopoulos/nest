import shutil
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nestd.context import AppContext
from nestd.pixies.agents import EDIT_TOOLS, PixieAgents
from nestd.pixies.files import PixieFiles
from nestd.pixies.models import (
    CreatePixie,
    CreateTeam,
    Pixie,
    UpdatePixie,
    UpdateTeam,
    WriteFile,
)
from nestd.pixies.prompt import CALL_PREAMBLE, NO_PIXIE_CALLS
from nestd.pixies.store import PixieStore
from nestd.pixies.team_store import TeamStore
from nestd.providers.base import CallRules
from nestd.sessions.models import Session, SessionState
from nestd.sessions.subagents import OfferedPixie
from tests.api_support import build_context
from tests.fakes import FakeClock, FakeSecretStore


@pytest.fixture
async def ctx(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> AsyncIterator[AppContext]:
    context = await build_context(tmp_path, clock, secrets)
    yield context
    await context.sessions.shutdown()
    await context.db.close()


@pytest.fixture
def agents(ctx: AppContext, clock: FakeClock) -> PixieAgents:
    return PixieAgents(
        PixieStore(ctx.db, clock), PixieFiles(ctx.paths.pixies_dir), TeamStore(ctx.db, clock)
    )


def chat(repo: str = "web") -> Session:
    now = datetime(2026, 10, 14, tzinfo=UTC)
    return Session(
        id="s1",
        repo=repo,
        title="t",
        prompt="p",
        mode="in_place",
        cwd=None,
        model=None,
        effort=None,
        permission_mode="default",
        provider="claude",
        state=SessionState.IDLE,
        worktree_path=None,
        branch=None,
        provider_session_id=None,
        created_at=now,
        updated_at=now,
        last_error=None,
    )


async def test_only_pixies_that_may_work_on_the_project_are_offered(
    ctx: AppContext, agents: PixieAgents
) -> None:
    for name, fields in (
        ("Everywhere", {}),
        ("Web", {"projects": ["web", "api"]}),
        ("Api", {"projects": ["api"]}),
        ("Hidden", {"hidden": True}),
        ("Nothing", {"project_access": "none"}),
        ("Reader", {"project_access": "read"}),
    ):
        await ctx.pixies.create(CreatePixie.model_validate({"name": name, **fields}))

    offered = await agents.for_session(chat("web"))

    assert list(offered.subagents) == ["everywhere", "web", "reader"]
    assert offered.teams == ()


async def test_a_definition_carries_the_pixie(ctx: AppContext, agents: PixieAgents) -> None:
    tester = await ctx.pixies.create(
        CreatePixie(
            name="Tester",
            soul="\n\n  You test everything.  \nSecond line.",
            model="opus",
            effort="high",
            permission_mode="acceptEdits",
            skills=["review"],
            disallowed_tools=["Bash(rm:*)"],
            project_access="read",
        )
    )
    memory = await ctx.pixies.read_file(tester.id, "memory")
    await ctx.pixies.write_file(
        tester.id, "memory", WriteFile(text="# Memory\n- likes ```fences```", hash=memory.hash)
    )
    plain_pixie = await ctx.pixies.create(CreatePixie(name="Plain"))
    soul = await ctx.pixies.read_file(plain_pixie.id, "soul")
    await ctx.pixies.write_file(plain_pixie.id, "soul", WriteFile(text="  \n", hash=soul.hash))

    offered = await agents.for_session(chat())
    sub = offered.subagents["tester"]
    plain = offered.subagents["plain"]

    assert sub.description == "Tester: You test everything."
    assert sub.prompt.startswith(
        CALL_PREAMBLE.format(name="Tester", slug="tester") + "\n" + NO_PIXIE_CALLS + "\n\n"
    )
    assert NO_PIXIE_CALLS == (
        "- You call no pixies. For help, use Claude Code's ordinary subagents, such as"
        " Explore or general-purpose."
    )
    assert "You test everything.  \nSecond line." in sub.prompt
    assert "- likes '''fences'''" in sub.prompt
    assert "## Your team" not in sub.prompt
    assert (sub.model, sub.effort, sub.permission_mode) == ("opus", "high", "acceptEdits")
    assert sub.skills == ("review",)
    assert sub.disallowed_tools == ("Bash(rm:*)", *EDIT_TOOLS)
    assert plain.description == "Plain"
    assert (plain.model, plain.effort, plain.skills, plain.disallowed_tools) == (
        None,
        None,
        (),
        (),
    )


async def test_a_leader_leads_its_available_members(ctx: AppContext, agents: PixieAgents) -> None:
    team = await ctx.teams.create(CreateTeam(name="QA crew", handle="qa"))
    lead, bugs, style, away, docs = [
        await ctx.pixies.create(CreatePixie(name=n, soul=f"You do {n}."))
        for n in ("Lead", "Bugs", "Style", "Away", "Docs")
    ]
    for pixie in (lead, bugs, style, away, docs):
        await ctx.pixies.update(pixie.id, UpdatePixie(team_id=team.id))
    await ctx.pixies.update(away.id, UpdatePixie(projects=["api"]))
    await ctx.pixies.update(style.id, UpdatePixie(hidden=True))

    offered = await agents.for_session(chat())
    prompt = offered.subagents["lead"].prompt

    # Away works elsewhere and Style is hidden; the leader is not its own member.
    assert prompt.endswith(
        "\n\n## Your team\nYou lead the team QA crew (@qa). Its members in this chat:\n"
        "- bugs: Bugs: You do Bugs.\n"
        "- docs: Docs: You do Docs.\n"
        "When a request comes for the team, decide which member does which part; you may do"
        " a part yourself. Call each member with the Agent tool, with `subagent_type` set to"
        " its slug and `run_in_background` set to false, and wait for its result. To continue"
        " a member you called earlier in this conversation, use SendMessage to its agent id"
        " instead of a new call. Then report what each member did and the combined result."
        " You call only your team's members; for other help, use Claude Code's ordinary"
        " subagents."
    )
    assert NO_PIXIE_CALLS not in prompt
    assert "## Your team" not in offered.subagents["bugs"].prompt
    assert [t.handle for t in offered.teams] == ["qa"]
    assert offered.teams[0].instruction == (
        "\n\n(The user called the team @qa, a team of pixies set up in Nest. Hand the whole"
        " request to its leader, the subagent lead, with the Agent tool and wait for its"
        " report. The leader decides which member does which part, calls them itself and puts"
        " their results together. Do not call its members (bugs, docs) yourself. When it"
        " reports, give its report and add a short summary of what happened.)"
    )


async def test_a_leader_alone_in_its_team(ctx: AppContext, agents: PixieAgents) -> None:
    team = await ctx.teams.create(CreateTeam(name="Solo act", handle="act"))
    lead = await ctx.pixies.create(CreatePixie(name="Lead"))
    await ctx.pixies.update(lead.id, UpdatePixie(team_id=team.id))

    offered = await agents.for_session(chat())

    assert "Its members in this chat:\nNo other member is in this chat.\n" in (
        offered.subagents["lead"].prompt
    )
    assert "Do not call its members" not in offered.teams[0].instruction
    assert offered.rules == CallRules(
        frozenset({"lead"}), frozenset({"lead"}), {"lead": frozenset()}
    )


async def test_a_team_whose_leader_is_not_available_is_left_out(
    ctx: AppContext, agents: PixieAgents
) -> None:
    team = await ctx.teams.create(CreateTeam(name="QA"))
    await ctx.teams.create(CreateTeam(name="Empty"))
    lead, member = [await ctx.pixies.create(CreatePixie(name=n)) for n in ("Lead", "Member")]
    for pixie in (lead, member):
        await ctx.pixies.update(pixie.id, UpdatePixie(team_id=team.id))
    await ctx.pixies.update(lead.id, UpdatePixie(project_access="none"))

    offered = await agents.for_session(chat())

    assert list(offered.subagents) == ["member"]
    assert offered.teams == ()


async def test_a_pixie_whose_folder_is_gone_is_left_out(
    ctx: AppContext, agents: PixieAgents
) -> None:
    gone = await ctx.pixies.create(CreatePixie(name="Gone"))
    await ctx.pixies.create(CreatePixie(name="Here"))
    shutil.rmtree(ctx.paths.pixies_dir / gone.id)

    assert list((await agents.for_session(chat())).subagents) == ["here"]


async def test_the_fingerprint_follows_pixie_changes(ctx: AppContext, agents: PixieAgents) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))
    first = await agents.for_session(chat())
    again = await agents.for_session(chat())
    soul = await ctx.pixies.read_file(pixie.id, "soul")
    await ctx.pixies.write_file(pixie.id, "soul", WriteFile(text="New soul.", hash=soul.hash))

    changed = await agents.for_session(chat())

    assert first.fingerprint == again.fingerprint
    assert changed.fingerprint != first.fingerprint


@pytest.mark.parametrize("model", ["default", "Default"])
async def test_the_default_model_inherits_the_chats(
    ctx: AppContext, agents: PixieAgents, model: str
) -> None:
    await ctx.pixies.create(CreatePixie(name="Tester", model=model))

    offered = await agents.for_session(chat())

    assert offered.subagents["tester"].model is None


async def test_the_team_call_names_the_leader_and_its_members_in_pixie_order(
    ctx: AppContext, agents: PixieAgents
) -> None:
    team = await ctx.teams.create(CreateTeam(name="QA"))
    first, second, third = [await ctx.pixies.create(CreatePixie(name=n)) for n in ("A", "B", "C")]
    for pixie in (third, first, second):
        await ctx.pixies.update(pixie.id, UpdatePixie(team_id=team.id))

    offered = await agents.for_session(chat())

    assert "the subagent c, with the Agent tool" in offered.teams[0].instruction
    assert "Do not call its members (a, b) yourself." in offered.teams[0].instruction


async def test_a_pixie_chat_gets_every_other_available_pixie_and_no_teams(
    ctx: AppContext, agents: PixieAgents
) -> None:
    created: dict[str, Pixie] = {}
    for name, fields in (
        ("Boss", {"projects": ["web"]}),
        ("Api", {"projects": ["api"]}),
        ("Hidden", {"hidden": True}),
        ("Nothing", {"project_access": "none"}),
        ("Reader", {"project_access": "read"}),
    ):
        pixie = await ctx.pixies.create(CreatePixie.model_validate({"name": name, **fields}))
        created[name] = pixie
    team = await ctx.teams.create(CreateTeam(name="QA", handle="qa"))
    await ctx.pixies.update(created["Api"].id, UpdatePixie(team_id=team.id))
    own = chat(f"pixie:{created['Boss'].id}").model_copy(update={"pixie_id": created["Boss"].id})

    offered = await agents.for_session(own)

    # Every project's pixie, but never itself, a hidden one or one without project access.
    assert list(offered.subagents) == ["api", "reader"]
    assert offered.teams == ()
    # A leader's team section belongs to project chats, where its team can be called.
    assert "## Your team" not in offered.subagents["api"].prompt
    # The pixie calls every other pixie; the ones it calls call none.
    assert offered.rules == CallRules(frozenset({"api", "reader"}), frozenset({"api", "reader"}))
    for sub in offered.subagents.values():
        assert NO_PIXIE_CALLS in sub.prompt


async def test_a_project_chat_knows_its_pixies_and_their_teams(
    ctx: AppContext, agents: PixieAgents
) -> None:
    team = await ctx.teams.create(CreateTeam(name="QA crew", handle="qa"))
    lonely = await ctx.teams.create(CreateTeam(name="Lonely", handle="lonely"))
    lead, bugs, solo, left = [
        await ctx.pixies.create(CreatePixie(name=n, soul=f"You do {n}."))
        for n in ("Lead", "Bugs", "Solo", "Left")
    ]
    for pixie in (lead, bugs):
        await ctx.pixies.update(pixie.id, UpdatePixie(team_id=team.id))
    await ctx.pixies.update(left.id, UpdatePixie(team_id=lonely.id))
    # Its team's leader works elsewhere, so the team is not offered and it is called alone.
    leader = await ctx.pixies.create(CreatePixie(name="Boss", projects=["api"]))
    await ctx.pixies.update(leader.id, UpdatePixie(team_id=lonely.id))
    await ctx.teams.update(lonely.id, UpdateTeam(leader_id=leader.id))

    offered = await agents.for_session(chat())

    assert dict(offered.pixies) == {
        "lead": OfferedPixie(lead.id, "lead", "Lead", team.id, "qa", leader=True),
        "bugs": OfferedPixie(bugs.id, "bugs", "Bugs", team.id, "qa"),
        "solo": OfferedPixie(solo.id, "solo", "Solo"),
        "left": OfferedPixie(left.id, "left", "Left"),
    }
    # A member says only its leader calls it, so the chat does not pick it alone.
    assert offered.subagents["bugs"].description == (
        "Bugs: You do Bugs. It is called only by its team's leader, as part of a team call to @qa."
    )
    assert offered.subagents["lead"].description == (
        "Lead: You do Lead. It leads the team @qa: a call to the team goes to it."
    )
    # The chat calls solo pixies and leaders; only a leader calls pixies, its members.
    assert offered.rules == CallRules(
        frozenset({"lead", "bugs", "solo", "left"}),
        frozenset({"lead", "solo", "left"}),
        {"lead": frozenset({"bugs"})},
    )
    for slug in ("bugs", "solo", "left"):
        assert NO_PIXIE_CALLS in offered.subagents[slug].prompt
    assert offered.subagents["solo"].description == "Solo: You do Solo."
    assert offered.subagents["left"].description == "Left: You do Left."
    assert "- bugs: Bugs: You do Bugs.\n" in offered.subagents["lead"].prompt


async def test_a_pixie_chat_records_no_pixies(ctx: AppContext, agents: PixieAgents) -> None:
    boss = await ctx.pixies.create(CreatePixie(name="Boss"))
    await ctx.pixies.create(CreatePixie(name="Other"))
    own = chat(f"pixie:{boss.id}").model_copy(update={"pixie_id": boss.id})

    offered = await agents.for_session(own)

    assert list(offered.subagents) == ["other"]
    assert offered.pixies == {}
