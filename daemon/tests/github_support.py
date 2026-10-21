"""Recorded `gh` output for issues and pull request reviews, as GitHub returns it (B101)."""

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "github"
REPO_URL = "https://github.com/me/repo.git"


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


def loaded(name: str) -> Any:  # noqa: ANN401 (JSON of any shape)
    return json.loads(fixture(name))


def issue_view(**fields: object) -> str:
    """`gh issue view 118 --json ...` output, with `fields` replaced."""
    data = loaded("issue_view")
    data.update(fields)
    return json.dumps(data)


def review_threads(
    threads: list[dict[str, Any]] | None = None,
    reviews: list[dict[str, Any]] | None = None,
    viewer: str = "giorgos",
) -> str:
    """The pull request review query's answer, for `viewer` (the user's gh login); threads
    and reviews replaced when given.
    """
    data = loaded("pr_review_threads")
    data["data"]["viewer"] = {"login": viewer}
    pr = data["data"]["repository"]["pullRequest"]
    if threads is not None:
        pr["reviewThreads"]["nodes"] = threads
    if reviews is not None:
        pr["reviews"]["nodes"] = reviews
    return json.dumps(data)


def thread(
    thread_id: str,
    *comments: tuple[str, str, str],
    path: str = "src/app.py",
    line: int | None = 5,
    resolved: bool = False,
) -> dict[str, Any]:
    """A review thread; each comment is (id, login, body) by a user."""
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": line is None,
        "path": path,
        "line": line,
        "originalLine": 4,
        "comments": {
            "nodes": [
                {
                    "id": comment_id,
                    "author": {"login": login, "__typename": "User"},
                    "body": body,
                    "url": f"https://github.com/me/repo/pull/7#discussion_{comment_id}",
                    "createdAt": "2026-10-20T11:00:00Z",
                }
                for comment_id, login, body in comments
            ]
        },
    }


NO_REVIEWS = review_threads([], [])
