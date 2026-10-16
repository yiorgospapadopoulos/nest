import pytest

from nestd.providers.base import CallRules, Subagent
from nestd.sessions.subagents import NO_AGENTS, ChatAgents, OfferedPixie, TeamCall

QA = TeamCall("qa", " [call qa]")
DOCS = TeamCall("docs-team", " [call docs]")
AGENTS = ChatAgents(teams=(QA, DOCS))


@pytest.mark.parametrize(
    ("text", "sent"),
    [
        ("@qa check this", "@qa check this [call qa]"),
        ("please ask @qa.", "please ask @qa. [call qa]"),
        ("ask @qa, then @qa again", "ask @qa, then @qa again [call qa]"),
        ("line\n@qa", "line\n@qa [call qa]"),
        ("(@qa)", "(@qa)"),
        ("mail me@qa now", "mail me@qa now"),
        ("@qa-lead is a pixie", "@qa-lead is a pixie"),
        ("@qa_x", "@qa_x"),
        ("@QA shouts", "@QA shouts"),
        ("@docs-team and @qa", "@docs-team and @qa [call qa] [call docs]"),
        ("no mention", "no mention"),
    ],
)
def test_team_mentions_append_their_call_once(text: str, sent: str) -> None:
    assert AGENTS.message(text) == sent


def test_no_teams_leaves_the_message_alone() -> None:
    assert NO_AGENTS.message("@qa hi") == "@qa hi"


def test_the_fingerprint_follows_the_definitions() -> None:
    tester = Subagent(description="T", prompt="You test.", permission_mode="default")
    same = ChatAgents({"tester": tester}, (QA,))
    other_prompt = ChatAgents(
        {"tester": Subagent(description="T", prompt="v2", permission_mode="default")}, (QA,)
    )
    other_team = ChatAgents({"tester": tester}, (DOCS,))

    assert same.fingerprint == ChatAgents({"tester": tester}, (QA,)).fingerprint
    assert same.fingerprint != other_prompt.fingerprint
    assert same.fingerprint != other_team.fingerprint
    assert same.fingerprint != NO_AGENTS.fingerprint


TESTER = Subagent(description="T", prompt="You test.", permission_mode="default")
LEAD = Subagent(description="L", prompt="You lead.", permission_mode="default")
CREW = ChatAgents(
    {"tester": TESTER, "lead": LEAD},
    (QA,),
    {
        "tester": OfferedPixie("p-tester", "tester", "Tester"),
        "lead": OfferedPixie("p-lead", "lead", "Lead", team_id="t-qa", team_handle="qa"),
    },
)


@pytest.mark.parametrize(
    ("text", "refusal"),
    [
        ("@lead plan this", "Lead is in @qa; call the team or a solo copy"),
        ("ask @lead.", "Lead is in @qa; call the team or a solo copy"),
        ("@leader is someone else", None),
        ("mail me@lead", None),
        ("@qa and @tester", None),
        ("no mention", None),
    ],
)
def test_a_team_member_is_called_only_through_its_team(text: str, refusal: str | None) -> None:
    assert CREW.member_call(text) == refusal


def test_mentioned_solo_pixies_and_team_members() -> None:
    assert CREW.mentioned_pixies("@tester then @tester, and @lead") == [CREW.pixies["tester"]]
    assert CREW.mentioned_pixies("@qa check") == []
    assert CREW.team_members("@qa check") == [CREW.pixies["lead"]]
    assert CREW.team_members("@tester only") == []


def test_each_pixie_has_its_own_fingerprint() -> None:
    changed = ChatAgents(
        {"tester": TESTER, "lead": Subagent(description="L", prompt="v2", permission_mode="plan")},
        (QA,),
        CREW.pixies,
    )

    assert CREW.pixie_fingerprint("tester") == changed.pixie_fingerprint("tester")
    assert CREW.pixie_fingerprint("lead") != changed.pixie_fingerprint("lead")
    assert CREW.pixie_fingerprint("tester") != CREW.pixie_fingerprint("lead")


def test_the_fingerprint_follows_the_call_rules() -> None:
    def rules(main: set[str], leaders: dict[str, frozenset[str]]) -> ChatAgents:
        return ChatAgents(
            CREW.subagents,
            CREW.teams,
            CREW.pixies,
            CallRules(frozenset({"tester", "lead"}), frozenset(main), leaders),
        )

    base = rules({"lead", "tester"}, {"lead": frozenset({"tester"})})

    assert (
        base.fingerprint == rules({"tester", "lead"}, {"lead": frozenset({"tester"})}).fingerprint
    )
    assert base.fingerprint != rules({"lead"}, {"lead": frozenset({"tester"})}).fingerprint
    assert base.fingerprint != rules({"lead", "tester"}, {}).fingerprint
    assert base.fingerprint != CREW.fingerprint


@pytest.mark.parametrize(
    ("caller", "target", "allowed"),
    [
        (None, "solo", True),
        (None, "bugs", False),
        (None, "Explore", True),
        ("lead", "bugs", True),
        ("lead", "solo", False),
        ("bugs", "lead", False),
        ("Explore", "bugs", False),
        ("Explore", "general-purpose", True),
    ],
)
def test_who_may_call_a_pixie(caller: str | None, target: str, allowed: bool) -> None:
    rules = CallRules(
        frozenset({"solo", "lead", "bugs"}),
        frozenset({"solo", "lead"}),
        {"lead": frozenset({"bugs"})},
    )

    assert rules.may_call(caller, target) is allowed
