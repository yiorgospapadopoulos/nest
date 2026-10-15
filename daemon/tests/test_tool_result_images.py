"""B59: images in tool results (a Read of a PNG, a screenshot tool) reach the clients."""

import base64
import logging
from pathlib import Path
from typing import Any, cast

import pytest
from claude_agent_sdk import ToolResultBlock, UserMessage

from nestd.attachments.store import (
    MAX_ATTACHMENT_BYTES,
    AttachmentNotFoundError,
    AttachmentStore,
)
from nestd.events.bus import EventBus
from nestd.providers import base
from nestd.sessions.live import LiveSession
from nestd.sessions.sink import SessionSink
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.api_client import running_api
from tests.fakes import FakeClock, FakeSecretStore
from tests.recording_hooks import RecordingHooks
from tests.test_claude_messages import translated
from tests.test_session_sink import RecordingTurns
from tests.test_session_store import new_session

PNG = base64.b64encode(b"\x89PNG-bytes").decode()


def image(data: object = PNG, media_type: object = "image/png") -> dict[str, Any]:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


async def test_a_tool_results_images_are_kept_for_the_session_to_store() -> None:
    content: list[dict[str, Any]] = [
        {"type": "text", "text": "Screenshot taken"},
        image(),
        image("R0lG", "image/gif"),
        image(data=3),
        image(media_type=None),
        {"type": "image", "source": "nope"},
        {"type": "image"},
    ]
    message = UserMessage(content=[ToolResultBlock(tool_use_id="t1", content=content)])

    assert await translated(message) == [
        (
            "message",
            (
                [
                    base.ToolResultBlock(
                        tool_use_id="t1",
                        # Images kept as images leave no placeholder in the text.
                        content="Screenshot taken\n[image]\n[image]\n[image]\n[image]",
                        image_data=[
                            base.ImageData(media_type="image/png", data=PNG),
                            base.ImageData(media_type="image/gif", data="R0lG"),
                        ],
                    )
                ],
                None,
            ),
        )
    ]


def test_the_image_data_never_reaches_the_payload_and_no_images_add_no_key() -> None:
    plain = base.ToolResultBlock(tool_use_id="t", content="ok")
    raw = base.ToolResultBlock(
        tool_use_id="t", content="", image_data=[base.ImageData(media_type="image/png", data=PNG)]
    )
    stored = base.ToolResultBlock(
        tool_use_id="t",
        content="",
        images=[base.ResultImage(attachment_id="a1", media_type="image/png")],
    )

    assert plain.model_dump(mode="json") == {
        "type": "tool_result",
        "tool_use_id": "t",
        "content": "ok",
        "is_error": False,
    }
    assert "image_data" not in raw.model_dump(mode="json")
    assert "images" not in raw.model_dump(mode="json")
    assert stored.model_dump(mode="json")["images"] == [
        {"attachment_id": "a1", "media_type": "image/png"}
    ]


@pytest.fixture
def attachments(db: Database, clock: FakeClock, tmp_path: Path) -> AttachmentStore:
    return AttachmentStore(db, clock, tmp_path / "attachments")


async def test_the_session_stores_tool_result_images_as_its_attachments(
    db: Database,
    clock: FakeClock,
    attachments: AttachmentStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    bus = EventBus(db, clock)
    sink = SessionSink(
        LiveSession(session.id),
        bus,
        store,
        RecordingTurns(),
        RecordingHooks(),
        None,
        attachments=attachments,
    )
    too_large = base64.b64encode(b"\0" * (MAX_ATTACHMENT_BYTES + 1)).decode()
    result = base.ToolResultBlock(
        tool_use_id="t1",
        content="Screenshot taken",
        image_data=[
            base.ImageData(media_type="image/png", data=PNG),
            base.ImageData(media_type="image/png", data="not base64!"),
            base.ImageData(media_type="image/png", data=too_large),
            base.ImageData(media_type="image/x-unknown", data=PNG),
        ],
    )

    with caplog.at_level(logging.WARNING):
        await sink.message([base.TextBlock(text="Here"), result], None)

    events = await bus.session_events(session.id)
    stored = cast(list[dict[str, Any]], events[0].payload["blocks"])[1]
    images = cast(list[dict[str, str]], stored["images"])
    assert [image["media_type"] for image in images] == ["image/png", "image/x-unknown"]
    first = await attachments.get(images[0]["attachment_id"])
    assert first.path.read_bytes() == b"\x89PNG-bytes"
    assert first.filename == "tool-result-1.png"
    assert first.session_id == session.id
    unknown = await attachments.get(images[1]["attachment_id"])
    assert unknown.filename == "tool-result-4"
    assert "image_data" not in stored
    assert caplog.text.count("could not keep an image") == 2


async def test_without_an_attachment_store_the_images_are_left_out(
    db: Database, clock: FakeClock
) -> None:
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    bus = EventBus(db, clock)
    sink = SessionSink(
        LiveSession(session.id), bus, store, RecordingTurns(), RecordingHooks(), None
    )
    result = base.ToolResultBlock(
        tool_use_id="t1",
        content="",
        image_data=[base.ImageData(media_type="image/png", data=PNG)],
    )

    await sink.message([result], None)

    events = await bus.session_events(session.id)
    assert events[0].payload["blocks"] == [
        {"type": "tool_result", "tool_use_id": "t1", "content": "", "is_error": False}
    ]


async def test_an_unknown_attachment_is_not_found(attachments: AttachmentStore) -> None:
    with pytest.raises(AttachmentNotFoundError, match="unknown attachment 'nope'"):
        await attachments.get("nope")


async def test_clients_fetch_an_attachments_file(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    async with running_api(tmp_path, clock, secrets) as api:
        saved = await api.ctx.attachments.save("shot.png", b"\x89PNG-bytes", "image/png")

        found = await api.http.get(f"/api/attachments/{saved.id}")
        missing = await api.http.get("/api/attachments/nope")
        del api.http.headers["Authorization"]
        anonymous = await api.http.get(f"/api/attachments/{saved.id}")

    assert found.status_code == 200
    assert found.content == b"\x89PNG-bytes"
    assert found.headers["content-type"] == "image/png"
    assert missing.status_code == 404
    assert missing.json() == {"detail": "unknown attachment 'nope'"}
    assert anonymous.status_code == 401


async def test_only_raster_images_are_shown_inline_and_nothing_runs_as_a_page(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    async with running_api(tmp_path, clock, secrets) as api:
        image = await api.ctx.attachments.save("shot.png", b"\x89PNG-bytes", "image/png")
        page = await api.ctx.attachments.save("x.html", b"<script>1</script>", "text/html")
        vector = await api.ctx.attachments.save("x.svg", b"<svg onload=1/>", "image/svg+xml")

        shown = await api.http.get(f"/api/attachments/{image.id}")
        html = await api.http.get(f"/api/attachments/{page.id}")
        svg = await api.http.get(f"/api/attachments/{vector.id}")

    assert shown.headers["content-type"] == "image/png"
    assert shown.headers["content-disposition"].startswith("inline")
    for response in (html, svg):
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"].startswith("attachment")
    for response in (shown, html, svg):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-security-policy"] == "sandbox; default-src 'none'"
