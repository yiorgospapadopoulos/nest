"""Stacked pull requests (B149): a chat on another chat's branch opens its pull request into
that branch, and moves onto main when the one under it merges, pushed only by a click.
"""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nestd.prs.github import parse_status
from tests.api_client import Api
from tests.async_support import until
from tests.fake_provider import edit, reply
from tests.fake_runner import pr_json
from tests.git_support import commit_file, git
from tests.test_api_review import api, approvals, approve, notified
from tests.test_api_sessions import create, reach

__all__ = ["api"]

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def session_of(api: Api, session_id: str) -> dict[str, Any]:
    return (await api.http.get(f"/api/sessions/{session_id}")).json()


async def chat(api: Api, files: dict[str, str], **fields: object) -> dict[str, Any]:
    """A worktree chat whose first turn writes `files`, waiting for its review."""
    api.provider.script(edit(files, reply("Done.")))
    session_id = str((await create(api, **fields))["id"])
    await reach(api, session_id, "idle")
    await notified(api, session_id, "review_ready")
    return await session_of(api, session_id)


async def opened(api: Api, session: dict[str, Any], base: str = "main") -> dict[str, Any]:
    """Approve the chat's work as a pull request, which GitHub then reports open."""
    approved = await approve(api, session["id"])
    assert approved.status_code == 200, approved.text
    head = git(Path(session["worktree_path"]), "rev-parse", "HEAD").strip()
    await set_pr(api, session["id"], headRefOid=head, baseRefName=base)
    return await session_of(api, session["id"])


async def set_pr(api: Api, session_id: str, **fields: object) -> None:
    """What GitHub reports for the chat's pull request, as the monitor records it."""
    session = await api.ctx.sessions.get(session_id)
    await api.ctx.prs.monitor.record(session, parse_status(pr_json(**fields), NOW))


def squash_into_main(api: Api, branch: str) -> None:
    """GitHub squash-merges `branch` into main."""
    repo = api.ctx.repos.get("repo").path
    git(repo, "merge", "--squash", "-q", branch)
    git(repo, "commit", "-q", "-m", f"Squashed {branch}")
    git(repo, "push", "-q", "origin", "main")


async def restacks(api: Api) -> list[dict[str, Any]]:
    return [a for a in await approvals(api, status="pending") if a["kind"] == "restack"]


def origin_branch(api: Api, branch: str) -> str:
    repo = api.ctx.repos.get("repo").path
    return git(repo, "ls-remote", "origin", f"refs/heads/{branch}").split()[0]


async def stacked(api: Api) -> tuple[dict[str, Any], dict[str, Any]]:
    """Chat A with an open pull request, and chat B started from A's branch."""
    a = await opened(api, await chat(api, {"a.txt": "a\n"}))
    b = await chat(api, {"b.txt": "b\n"}, base=a["branch"])
    return a, b


async def test_a_chat_on_another_chats_branch_opens_its_pull_request_into_it(api: Api) -> None:
    a, b = await stacked(api)

    assert b["stack"] == {"parent": a["id"], "parent_branch": a["branch"], "restack": None}
    approved = await approve(api, b["id"])

    assert approved.status_code == 200, approved.text
    create_call = api.runner.gh_calls("create")[-1]
    assert create_call[create_call.index("--base") + 1] == a["branch"]


async def test_a_stacked_chat_waits_for_the_pull_request_under_it(api: Api) -> None:
    a = await chat(api, {"a.txt": "a\n"})
    b = await chat(api, {"b.txt": "b\n"}, base=a["branch"])

    refused = await approve(api, b["id"])

    assert refused.status_code == 409
    assert "open that chat's pull request first" in refused.json()["detail"]


async def test_merging_the_one_under_rebases_by_itself_and_pushes_on_the_click(api: Api) -> None:
    a, b = await stacked(api)
    b = await opened(api, b, base=a["branch"])
    pushed_before = origin_branch(api, b["branch"])
    squash_into_main(api, a["branch"])

    await set_pr(api, a["id"], state="MERGED", headRefOid=a["pr"]["head_sha"])

    async def moved() -> bool:
        stack = (await session_of(api, b["id"]))["stack"]
        return stack["restack"] is not None and stack["restack"]["rebased"] is not None

    await until(moved)
    worktree = Path(b["worktree_path"])
    # B's own commit now sits on main, which has A's work squashed; nothing was pushed.
    git(worktree, "merge-base", "--is-ancestor", "origin/main", "HEAD")
    assert git(worktree, "log", "--format=%s", "origin/main..HEAD").splitlines() == ["Fix the bug"]
    assert origin_branch(api, b["branch"]) == pushed_before
    (ask,) = await restacks(api)
    assert (ask["session_id"], ask["payload"]["base"], ask["payload"]["rebased"]) == (
        b["id"],
        "main",
        True,
    )

    pushed = await api.http.post(f"/api/sessions/{b['id']}/restack")

    assert pushed.status_code == 200, pushed.text
    assert pushed.json()["stack"] == {"parent": None, "parent_branch": None, "restack": None}
    assert origin_branch(api, b["branch"]) == git(worktree, "rev-parse", "HEAD").strip()
    edit_call = api.runner.gh_calls("edit")[-1]
    assert edit_call[edit_call.index("--base") + 1] == "main"
    assert await restacks(api) == []


async def test_a_chat_on_the_stacked_one_follows_it_in_order(api: Api) -> None:
    a, b = await stacked(api)
    b = await opened(api, b, base=a["branch"])
    c = await chat(api, {"c.txt": "c\n"}, base=b["branch"])
    squash_into_main(api, a["branch"])

    await set_pr(api, a["id"], state="MERGED", headRefOid=a["pr"]["head_sha"])

    def on_main() -> bool:
        found = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"],  # noqa: S607
            cwd=c["worktree_path"],
            check=False,
        )
        return found.returncode == 0

    async def done() -> bool:
        return on_main() and (await session_of(api, c["id"]))["stack"]["restack"] is None

    await until(done)
    # C, with no pull request, needed no push: it sits on B's rebased branch.
    git(Path(c["worktree_path"]), "merge-base", "--is-ancestor", b["branch"], "HEAD")
    stack = (await session_of(api, c["id"]))["stack"]
    assert (stack["parent"], stack["restack"]) == (b["id"], None)
    assert [ask["session_id"] for ask in await restacks(api)] == [b["id"]]


async def test_a_rebase_that_conflicts_waits_with_the_reason(api: Api) -> None:
    a, b = await stacked(api)
    b = await opened(api, b, base=a["branch"])
    repo = api.ctx.repos.get("repo").path
    squash_into_main(api, a["branch"])
    # main adds B's file in another way after A's merge.
    (repo / "b.txt").write_text("main's own\n", encoding="utf-8")
    git(repo, "add", "b.txt")
    git(repo, "commit", "-q", "-m", "Add b.txt on main")
    git(repo, "push", "-q", "origin", "main")

    await set_pr(api, a["id"], state="MERGED", headRefOid=a["pr"]["head_sha"])

    async def asked() -> bool:
        return len(await restacks(api)) == 1

    await until(asked)
    (ask,) = await restacks(api)
    assert ask["payload"]["rebased"] is False
    assert "stopped on conflicts: b.txt" in ask["payload"]["error"]
    # The rebase was undone: B's folder is on its branch, as before.
    worktree = Path(b["worktree_path"])
    assert git(worktree, "status", "--porcelain").strip() == ""
    assert git(worktree, "rev-parse", "HEAD").strip() == b["pr"]["head_sha"]

    clicked = await api.http.post(f"/api/sessions/{b['id']}/restack")

    assert clicked.status_code == 409
    assert clicked.json()["code"] == "restack_failed"


async def test_commits_the_pull_request_does_not_have_are_never_force_pushed(api: Api) -> None:
    """B159 P-3: the agent commits on the Mac after the pull request was opened; moving the
    branch would rebase that commit too, and the click would force-push it unseen.
    """
    a, b = await stacked(api)
    b = await opened(api, b, base=a["branch"])
    worktree = Path(b["worktree_path"])
    commit_file(worktree, "unseen.txt", "never reviewed\n")
    head = git(worktree, "rev-parse", "HEAD").strip()
    pushed_before = origin_branch(api, b["branch"])
    squash_into_main(api, a["branch"])

    await set_pr(api, a["id"], state="MERGED", headRefOid=a["pr"]["head_sha"])

    async def asked() -> bool:
        return len(await restacks(api)) == 1

    await until(asked)
    (ask,) = await restacks(api)
    assert ask["payload"]["rebased"] is False
    assert "not where its pull request is" in ask["payload"]["error"]
    assert git(worktree, "rev-parse", "HEAD").strip() == head

    clicked = await api.http.post(f"/api/sessions/{b['id']}/restack")

    assert clicked.status_code == 409
    assert clicked.json()["code"] == "restack_failed"
    assert origin_branch(api, b["branch"]) == pushed_before
    assert api.runner.gh_calls("edit") == []


async def test_uncommitted_changes_keep_the_branch_where_it_is(api: Api) -> None:
    a, b = await stacked(api)
    (Path(b["worktree_path"]) / "b.txt").write_text("still editing\n", encoding="utf-8")
    git(Path(b["worktree_path"]), "add", "b.txt")
    head = git(Path(b["worktree_path"]), "rev-parse", "HEAD").strip()
    squash_into_main(api, a["branch"])

    await set_pr(api, a["id"], state="MERGED", headRefOid=a["pr"]["head_sha"])

    async def asked() -> bool:
        return len(await restacks(api)) == 1

    await until(asked)
    (ask,) = await restacks(api)
    assert "uncommitted changes" in ask["payload"]["error"]
    assert git(Path(b["worktree_path"]), "rev-parse", "HEAD").strip() == head


async def test_a_stacked_pull_request_is_not_merged_while_its_branch_waits_to_move(
    api: Api,
) -> None:
    a, b = await stacked(api)
    b = await opened(api, b, base=a["branch"])
    merges = [x for x in await approvals(api, status="pending") if x["kind"] == "merge"]
    assert [x["session_id"] for x in merges] == [a["id"], b["id"]]
    (Path(b["worktree_path"]) / "b.txt").write_text("still editing\n", encoding="utf-8")
    squash_into_main(api, a["branch"])

    await set_pr(api, a["id"], state="MERGED", headRefOid=a["pr"]["head_sha"])

    async def asked() -> bool:
        return len(await restacks(api)) == 1

    await until(asked)
    # B's pull request still points at A's merged branch: no merge until it moves.
    assert [x for x in await approvals(api, status="pending") if x["kind"] == "merge"] == []
    refused = await api.http.post(f"/api/sessions/{b['id']}/merge")
    assert refused.status_code == 409
    assert api.runner.gh_calls("merge") == []
