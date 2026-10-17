import pytest

from nestd.sessions.titles import MAX_TITLE_LENGTH, MAX_TITLE_WORDS, short_title


@pytest.mark.parametrize(
    ("prompt", "title"),
    [
        ("Fix the bug", "Fix the bug"),
        ("Fix the bug\nDetails here", "Fix the bug"),
        ("Fix the login bug. It happens when the token expires.", "Fix the login bug"),
        ("please fix the flaky test in test_api.py", "Fix the flaky test"),
        ("Can you add dark mode to the settings page?", "Add dark mode to the settings"),
        ("could you please update the README", "Update the README"),
        ("I want you to refactor the session manager", "Refactor the session manager"),
        ("I'd like you to rename the config loader", "Rename the config loader"),
        ("First, read AGENTS.md and the plan", "Read AGENTS.md"),
        ("Hi Claude,\n\nplease bump the version to 0.2.0", "Bump the version to 0.2.0"),
        ("Hey! Can you check why CI fails on main?", "Check why CI fails on main"),
        ("ok so now we need to ship the release notes", "Ship the release notes"),
        ("Let's add a /health endpoint", "Add a /health endpoint"),
        ("Let\u2019s add a changelog", "Add a changelog"),
        ("Fix the thing\u2026", "Fix the thing"),
        ("Why does `make check` fail on a fresh clone?", "Why does `make check` fail"),
        ("## Fix the login redirect\nDetails follow", "Fix the login redirect"),
        ("- add pagination to /api/sessions", "Add pagination to /api/sessions"),
        ("Update README.md and docs/decisions.md", "Update README.md"),
        ("Use e.g. pytest fixtures here. Then run it", "Use e.g. pytest fixtures here"),
        ("   fix    the   spacing\tissue   ", "Fix the spacing issue"),
        ("First-time setup wizard is broken", "First-time setup wizard"),
        ("Please.", "Please"),
        ("...", "Untitled"),
        (
            "Investigate why the websocket reconnect loop leaks subscribers after the Mac sleeps",
            "Investigate why the websocket",
        ),
        (
            "please can you look into the problem where approvals expire too early, and fix it",
            "Look into the problem where",
        ),
        ("a" * 60, "A" + "a" * 31),
        (
            "Fix the bug that breaks everything, badly, really really badly",
            "Fix the bug that breaks",
        ),
        ("Hi", "Hi"),
        ("Do it", "Do it"),
        ("Do it.\nFix the login bug", "Fix the login bug"),
        ("@qa", "@qa"),
        ("Use the Bash tool", "Use the Bash tool"),
        ("<pasted_content>\n</pasted_content>", "Untitled"),
        ("Rename the data area", "Rename the data area"),
        ("Fix it to -", "Fix"),
        ("Rock and roll", "Rock"),
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
    assert len(title.split()) <= MAX_TITLE_WORDS
    assert title[-1].isalnum()


# Real first prompts from the user's chats and the titles they should get.
@pytest.mark.parametrize(
    ("prompt", "title"),
    [
        ("start b84 at a worktree while in main branch b83 is workign", "Start b84 at a worktree"),
        (
            "can we do b72 in a worktree while b71 is being made currently in the main branch?",
            "Do b72 in a worktree",
        ),
        ("can i start b81 while b79 is being done in main branch", "Start b81"),
        (
            "Look over this project for me: list its files, count the lines in each",
            "Look over this project",
        ),
        ("Run sleep 10 && echo hi in bash, then summarize", "Run sleep 10 && echo hi"),
        (
            "Initialize this folder as a git repository: run git init with main",
            "Initialize this folder as a git",
        ),
        (
            "Use the AskUserQuestion tool to ask me whether dialogue branches should be stored"
            " as a DAG",
            "Ask me whether dialogue branches",
        ),
        (
            "There is work being done right now. I for phase seven template check",
            "Work being done right now",
        ),
        ("Hello. What are the contents of this folder", "What are the contents"),
        (
            '\n\n<pasted_content id="4b09">\nRun an independent audit of harness (this repo)'
            " and come back with a report.",
            "Run an independent audit",
        ),
        ("write the plan up as an artifact", "Write the plan up"),
        ("@qa review hello.py", "Review hello.py"),
        (
            "@test-team-1 do 2 of the pixies inside here to doemthing",
            "Do 2 of the pixies inside",
        ),
        ("commit the uncommited changes", "Commit the uncommited changes"),
        ("hey make a one line change", "Make a one line change"),
        ("Reply with the single word ok.", "Reply with the single word ok"),
        (
            "Use only the Glob tool to list the files at the top level of the repo",
            "List the files at the top",
        ),
        ("Can we add something like monos to my harness?", "Add something like monos"),
        (
            "Review Phase 7.1 (documentary context for Resource Mobilization)",
            "Review Phase 7.1",
        ),
        (
            "Okay, so uh, the goal is to implement phase six of the plan",
            "The goal is to implement phase",
        ),
        (
            "make it so every time someone types kats in the terminal",
            "Every time someone types kats",
        ),
        ("what are the undone blocks", "What are the undone blocks"),
        (
            "I have b55, i cannot understand the difference between branch and worktrees",
            "I have b55",
        ),
    ],
)
def test_real_prompts_get_minimal_titles(prompt: str, title: str) -> None:
    assert short_title(prompt) == title
