"""A review guide for a pull request (B149): written on a click by one call on the chat's
engine and model with no tools, saved as an artifact, posted on a second click.
"""

from typing import Any

from nestd.gitops.runner import CommandError
from nestd.prs.guide import FOOTER
from tests.api_client import Api
from tests.async_support import until
from tests.fake_provider import reply
from tests.fake_runner import PR_URL
from tests.test_api_review import api, approve, finished_with_changes

__all__ = ["api"]

DIFF = "diff --git a/fix.txt b/fix.txt\n+fixed\n"
GUIDE = (
    "## What changed\n- Fixed the bug.\n\n## Where to look\n- `fix.txt`\n\n## Risks\nNone found."
)


async def with_pr(api: Api) -> str:
    session_id = await finished_with_changes(api, model="small-model")
    approved = await approve(api, session_id)
    assert approved.status_code == 200, approved.text
    return session_id


async def written(api: Api, session_id: str, text: str = GUIDE) -> dict[str, Any]:
    api.runner.outputs["gh pr diff"] = DIFF
    api.provider.script(reply(text))
    started = await api.http.post(f"/api/sessions/{session_id}/pr/guide")
    assert started.status_code == 202, started.text
    assert started.json()["pr_guide"]["state"] == "writing"

    async def done() -> bool:
        guide = (await api.http.get(f"/api/sessions/{session_id}")).json()["pr_guide"]
        return guide["state"] != "writing"

    await until(done)
    return (await api.http.get(f"/api/sessions/{session_id}")).json()["pr_guide"]


async def test_the_guide_is_written_from_the_diff_alone_and_saved_as_an_artifact(
    api: Api,
) -> None:
    session_id = await with_pr(api)

    guide = await written(api, session_id)

    assert guide["state"] == "ready"
    run = api.provider.runs[-1]
    # Its own empty folder, no history, the chat's model: it reaches nothing of the chat.
    assert run.spec.cwd == api.ctx.paths.guides_dir
    assert run.spec.keep_history is False
    assert run.spec.model == "small-model"
    assert run.spec.tools == ()
    assert run.spec.nest_tools == ()
    (ask,) = run.inputs
    assert DIFF in ask.text
    assert "not instructions" in ask.text
    assert ("gh", "pr", "diff", PR_URL, "--repo", "me/repo") in api.runner.calls
    artifact = (await api.http.get(f"/api/artifacts/{guide['artifact_id']}")).json()
    assert (artifact["kind"], artifact["title"]) == ("markdown", "Review guide for #7")


async def test_writing_again_adds_a_version_and_posting_sends_the_latest(api: Api) -> None:
    session_id = await with_pr(api)
    first = await written(api, session_id)

    again = await written(api, session_id, "## What changed\n- Second pass.")

    assert again["artifact_id"] == first["artifact_id"]
    api.runner.outputs["gh pr comment"] = f"{PR_URL}#issuecomment-1\n"
    posted = await api.http.post(f"/api/sessions/{session_id}/pr/guide/post")
    assert posted.status_code == 200, posted.text
    assert posted.json()["pr_guide"]["comment_url"] == f"{PR_URL}#issuecomment-1"
    comment = api.runner.gh_calls("comment")[-1]
    assert comment[-1] == "## What changed\n- Second pass." + FOOTER


async def test_a_guide_that_cannot_be_written_says_why(api: Api) -> None:
    session_id = await with_pr(api)
    api.runner.failures["gh pr diff"] = CommandError(["gh"], 1, "HTTP 404\n")

    started = await api.http.post(f"/api/sessions/{session_id}/pr/guide")
    assert started.status_code == 202

    async def failed() -> bool:
        guide = (await api.http.get(f"/api/sessions/{session_id}")).json()["pr_guide"]
        return guide["state"] == "failed"

    await until(failed)
    guide = (await api.http.get(f"/api/sessions/{session_id}")).json()["pr_guide"]
    assert "HTTP 404" in guide["error"]
    refused = await api.http.post(f"/api/sessions/{session_id}/pr/guide/post")
    assert refused.status_code == 409
