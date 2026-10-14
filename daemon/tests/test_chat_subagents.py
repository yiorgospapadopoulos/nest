import pytest

from harness.providers.base import Subagent
from harness.sessions.subagents import NO_AGENTS, ChatAgents, TeamCall

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
