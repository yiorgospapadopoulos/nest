import pytest

from nestd.sessions.titles import MAX_TITLE_LENGTH, short_title


@pytest.mark.parametrize(
    ("prompt", "title"),
    [
        ("Fix the bug", "Fix the bug"),
        ("Fix the bug\nDetails here", "Fix the bug"),
        ("Fix the login bug. It happens when the token expires.", "Fix the login bug"),
        ("please fix the flaky test in test_api.py", "Fix the flaky test in test_api.py"),
        ("Can you add dark mode to the settings page?", "Add dark mode to the settings page"),
        ("could you please update the README", "Update the README"),
        ("I want you to refactor the session manager", "Refactor the session manager"),
        ("I'd like you to rename the config loader", "Rename the config loader"),
        ("First, read AGENTS.md and the plan", "Read AGENTS.md and the plan"),
        ("Hi Claude,\n\nplease bump the version to 0.2.0", "Bump the version to 0.2.0"),
        ("Hey! Can you check why CI fails on main?", "Check why CI fails on main"),
        ("ok so now we need to ship the release notes", "Ship the release notes"),
        ("Let's add a /health endpoint", "Add a /health endpoint"),
        ("Let\u2019s add a changelog", "Add a changelog"),
        ("Fix the thing\u2026", "Fix the thing"),
        (
            "Why does `make check` fail on a fresh clone?",
            "Why does `make check` fail on a fresh clone",
        ),
        ("## Fix the login redirect\nDetails follow", "Fix the login redirect"),
        ("- add pagination to /api/sessions", "Add pagination to /api/sessions"),
        ("Update README.md and docs/notes.md", "Update README.md and docs/notes.md"),
        ("Use e.g. pytest fixtures here. Then run it", "Use e.g. pytest fixtures here"),
        ("   fix    the   spacing\tissue   ", "Fix the spacing issue"),
        ("First-time setup wizard is broken", "First-time setup wizard is broken"),
        ("Please.", "Please"),
        ("...", "Untitled"),
        (
            "Investigate why the websocket reconnect loop leaks subscribers after the Mac sleeps",
            "Investigate why the websocket reconnect loop",
        ),
        (
            "please can you look into the problem where approvals expire too early, and fix it",
            "Look into the problem where approvals expire too",
        ),
        ("a" * 60, "A" + "a" * 47),
        (
            "Fix the bug that breaks everything, badly, really really badly",
            "Fix the bug that breaks everything, badly",
        ),
    ],
)
def test_short_titles(prompt: str, title: str) -> None:
    assert short_title(prompt) == title


@pytest.mark.parametrize(
    "prompt",
    [
        "Please implement the whole B20 block from the plan, including tests and docs",
        "Can you go through every module and make sure that the types are strict enough?",
        "x " * 100,
    ],
)
def test_titles_never_exceed_the_limit_or_end_in_punctuation(prompt: str) -> None:
    title = short_title(prompt)

    assert 0 < len(title) <= MAX_TITLE_LENGTH
    assert title[-1].isalnum()
