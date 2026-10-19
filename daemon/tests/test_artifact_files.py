"""The files of a multi-file HTML page (B88 stage 3): checked paths, encodings, mime types
from the extension, and the caps of a version.
"""

import base64

import pytest
from pydantic import JsonValue

from nestd.artifacts.files import (
    FILES_MAX,
    PATH_MAX,
    VERSION_MAX,
    FileData,
    PageFile,
    checked_files,
    mime_of,
)
from nestd.artifacts.models import ArtifactNotFoundError, InvalidArtifactError
from nestd.context import AppContext
from tests.fake_provider import FakeProvider
from tests.pixie_nest_support import ctx, provider
from tests.test_artifacts import chat, create, fail_saving_versions, folder
from tests.test_artifacts import refused as tool_refused

__all__ = ["ctx", "provider"]

PAGE = '<!doctype html><script src="app.js"></script><img src="img/logo.png">'


def refused(files: list[dict[str, JsonValue]], content_size: int = 10) -> str:
    with pytest.raises(InvalidArtifactError) as refusal:
        checked_files(files, content_size)
    return str(refusal.value)


def test_files_are_decoded_with_their_mime_types() -> None:
    files = checked_files(
        [
            {"path": "app.js", "content": "start()"},
            {"path": "css/style.css", "content": "body{}", "encoding": "utf8"},
            {
                "path": "img/logo.PNG",
                "content": base64.b64encode(b"\x89PNG").decode(),
                "encoding": "base64",
            },
            {"path": "data.v2.json", "content": "{}"},
            {"path": "notes", "content": "x"},
        ],
        100,
    )

    assert files == [
        FileData("app.js", b"start()", "text/javascript"),
        FileData("css/style.css", b"body{}", "text/css"),
        FileData("img/logo.PNG", b"\x89PNG", "image/png"),
        FileData("data.v2.json", b"{}", "application/json"),
        FileData("notes", b"x", "application/octet-stream"),
    ]
    assert files[0].listed == PageFile(path="app.js", size=7, mime="text/javascript")


@pytest.mark.parametrize(
    ("path", "mime"),
    [
        ("a.js", "text/javascript"),
        ("a.css", "text/css"),
        ("a.json", "application/json"),
        ("a.csv", "text/csv"),
        ("a.txt", "text/plain"),
        ("a.md", "text/markdown"),
        ("a.svg", "image/svg+xml"),
        ("a.png", "image/png"),
        ("a.jpg", "image/jpeg"),
        ("a.jpeg", "image/jpeg"),
        ("a.gif", "image/gif"),
        ("a.webp", "image/webp"),
        ("a.woff", "font/woff"),
        ("a.woff2", "font/woff2"),
        ("a.html", "text/html"),
        ("a.exe", "application/octet-stream"),
        ("Makefile", "application/octet-stream"),
    ],
)
def test_the_mime_type_comes_from_a_fixed_table(path: str, mime: str) -> None:
    assert mime_of(path) == mime


def test_no_files_is_fine() -> None:
    assert checked_files([], 5) == []


@pytest.mark.parametrize(
    "path",
    [
        "/abs.js",
        "../up.js",
        "a/../b.js",
        "./a.js",
        "a/./b.js",
        "a//b.js",
        "a/",
        "",
        "sp ace.js",
        "back\\slash.js",
        "é.js",
        "a" * (PATH_MAX + 1),
    ],
)
def test_bad_paths_are_refused(path: str) -> None:
    message = refused([{"path": path, "content": "x"}])

    assert message.startswith(f"files[0].path {path!r} must be a relative path")
    assert "letters, digits, dot, dash and underscore" in message


def test_a_path_of_exactly_the_limit_is_fine() -> None:
    [file] = checked_files([{"path": "a" * PATH_MAX, "content": "x"}], 1)

    assert len(file.path) == PATH_MAX


def test_paths_must_be_unique_ignoring_case() -> None:
    message = refused([{"path": "App.js", "content": "x"}, {"path": "app.js", "content": "y"}])

    assert message == "files[1].path 'app.js' is used twice (paths are compared ignoring case)"


def test_bad_base64_is_refused() -> None:
    message = refused([{"path": "a.png", "content": "not base64!", "encoding": "base64"}])

    assert message == "files[0].content is not valid base64"


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ([{"path": "a.js"}], "files[0].content: Field required."),
        (
            [{"path": "a.js", "content": "x", "encoding": "hex"}],
            "files[0].encoding: Input should be",
        ),
        ([{"path": "a.js", "content": "x", "mode": 1}], "files[0].mode: Extra inputs"),
        ([{"path": "a.js", "content": "half \ud800"}], "files[0].content is not valid text"),
    ],
)
def test_malformed_entries_are_refused(files: list[dict[str, JsonValue]], message: str) -> None:
    assert message in refused(files)


def test_at_most_100_files() -> None:
    files: list[dict[str, JsonValue]] = [
        {"path": f"f{i}.txt", "content": "x"} for i in range(FILES_MAX + 1)
    ]

    assert refused(files) == f"a page has at most {FILES_MAX} files; this one has {FILES_MAX + 1}"
    assert len(checked_files(files[:FILES_MAX], 1)) == FILES_MAX


def test_a_version_holds_at_most_16_mib_with_its_files() -> None:
    big = base64.b64encode(b"a" * (VERSION_MAX - 100)).decode()
    files: list[dict[str, JsonValue]] = [{"path": "big.bin", "content": big, "encoding": "base64"}]

    checked_files(files, 100)
    message = refused(files, 101)

    assert message == (
        f"the page and its files are {VERSION_MAX + 1} bytes; a version holds at most"
        f" {VERSION_MAX} bytes (16 MiB) in all"
    )


def page_files() -> list[JsonValue]:
    return [
        {"path": "app.js", "content": "start()"},
        {
            "path": "img/logo.png",
            "content": base64.b64encode(b"\x89PNG").decode(),
            "encoding": "base64",
        },
    ]


async def test_an_html_page_saves_its_files_with_the_version(
    ctx: AppContext, provider: FakeProvider
) -> None:
    _, tools = await chat(ctx, provider)

    artifact_id = await create(tools, kind="html", content=PAGE, files=page_files())

    root = folder(ctx, artifact_id)
    content = await ctx.artifacts.content(artifact_id, 1)
    assert (root / "v1.html").read_text(encoding="utf-8") == PAGE
    assert (root / "v1" / "app.js").read_bytes() == b"start()"
    assert (root / "v1" / "img" / "logo.png").read_bytes() == b"\x89PNG"
    assert content.files == [
        PageFile(path="app.js", size=7, mime="text/javascript"),
        PageFile(path="img/logo.png", size=4, mime="image/png"),
    ]
    assert (await ctx.artifacts.detail(artifact_id)).versions[0].size == len(PAGE)


async def test_an_update_without_files_keeps_none(ctx: AppContext, provider: FakeProvider) -> None:
    _, tools = await chat(ctx, provider)
    artifact_id = await create(tools, kind="html", content=PAGE, files=page_files())

    await tools["update_artifact"].handler({"artifact_id": artifact_id, "content": PAGE})
    await tools["update_artifact"].handler(
        {
            "artifact_id": artifact_id,
            "content": PAGE,
            "files": [{"path": "b.css", "content": "p{}"}],
        }
    )

    second = await ctx.artifacts.content(artifact_id, 2)
    third = await ctx.artifacts.content(artifact_id, 3)
    first = await ctx.artifacts.content(artifact_id, 1)
    assert second.files == []
    assert [f.path for f in third.files] == ["b.css"]
    assert [f.path for f in first.files] == ["app.js", "img/logo.png"]
    assert not (folder(ctx, artifact_id) / "v2").exists()


@pytest.mark.parametrize("kind", ["markdown", "document", "slides"])
async def test_only_html_pages_take_files(
    ctx: AppContext, provider: FakeProvider, kind: str
) -> None:
    _, tools = await chat(ctx, provider)
    existing = await create(tools, kind=kind, content="# One")

    on_create = await tool_refused(
        tools, "create_artifact", title="T", kind=kind, content="# x", files=page_files()
    )
    on_update = await tool_refused(
        tools, "update_artifact", artifact_id=existing, content="# x", files=page_files()
    )

    expected = f"only html pages take files; a {kind} artifact cannot"
    assert on_create.startswith(expected)
    assert on_update.startswith(expected)
    assert (await ctx.artifacts.detail(existing)).version_count == 1


async def test_bad_files_save_nothing(ctx: AppContext, provider: FakeProvider) -> None:
    _, tools = await chat(ctx, provider)

    message = await tool_refused(
        tools, "create_artifact", title="T", kind="html", content=PAGE, files=[{"path": "../x"}]
    )

    assert message.startswith("files[0]")
    assert await ctx.artifacts.list_artifacts() == []
    assert list(ctx.paths.artifacts_dir.iterdir()) == []


async def test_a_failed_save_leaves_no_files(
    ctx: AppContext, provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, tools = await chat(ctx, provider)
    artifact_id = await create(tools, kind="html", content=PAGE)

    fail_saving_versions(monkeypatch)
    with pytest.raises(OSError, match="disk full"):
        await tools["update_artifact"].handler(
            {"artifact_id": artifact_id, "content": PAGE, "files": page_files()}
        )
    with pytest.raises(OSError, match="disk full"):
        await create(tools, kind="html", content=PAGE, files=page_files())

    monkeypatch.undo()
    assert [p.name for p in ctx.paths.artifacts_dir.iterdir()] == [artifact_id]
    assert sorted(p.name for p in folder(ctx, artifact_id).iterdir()) == ["v1.html"]
    assert await ctx.db.fetch_all("SELECT * FROM artifact_files") == []


async def test_deleting_the_artifact_deletes_its_files(
    ctx: AppContext, provider: FakeProvider
) -> None:
    _, tools = await chat(ctx, provider)
    artifact_id = await create(tools, kind="html", content=PAGE, files=page_files())

    await ctx.artifacts.delete(artifact_id)

    assert await ctx.db.fetch_all("SELECT * FROM artifact_files") == []
    assert not folder(ctx, artifact_id).exists()


async def test_a_file_is_read_by_its_path(ctx: AppContext, provider: FakeProvider) -> None:
    _, tools = await chat(ctx, provider)
    artifact_id = await create(tools, kind="html", content=PAGE, files=page_files())

    logo = await ctx.artifacts.file(artifact_id, 1, "img/logo.png")

    assert logo == FileData("img/logo.png", b"\x89PNG", "image/png")
    for version, path in ((1, "img/LOGO.png"), (1, "nope.js"), (2, "app.js")):
        with pytest.raises(ArtifactNotFoundError):
            await ctx.artifacts.file(artifact_id, version, path)
    (folder(ctx, artifact_id) / "v1" / "app.js").unlink()
    with pytest.raises(ArtifactNotFoundError, match=r"the file 'app\.js' of version 1 is missing"):
        await ctx.artifacts.file(artifact_id, 1, "app.js")
    with pytest.raises(ArtifactNotFoundError, match=r"the file 'app.js' of version 1 is missing"):
        await ctx.artifacts.content(artifact_id, 1)
