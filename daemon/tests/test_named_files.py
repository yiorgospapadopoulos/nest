"""The viewer reads only files inside a chat's folder or its attachments (B144)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.sessions.named_files import NamedFileNotFoundError, named_file
from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    chat = tmp_path / "chat"
    (chat / "src").mkdir(parents=True)
    (chat / "src" / "app.py").write_text("print(1)\n")
    (tmp_path / "secret.txt").write_text("no")
    (chat / "out").symlink_to(tmp_path / "secret.txt")
    return chat


def test_a_file_inside_the_folder_by_relative_or_absolute_path(folder: Path) -> None:
    inside = (folder / "src" / "app.py").resolve()

    assert named_file("src/app.py", folder, ()) == inside
    assert named_file(str(folder / "src" / "app.py"), folder, ()) == inside


@pytest.mark.parametrize(
    "path",
    ["../secret.txt", "src/../../secret.txt", "out", "src", "missing.py", "/etc/hosts", "a\0b"],
)
def test_anything_outside_or_not_a_file_is_not_found(folder: Path, path: str) -> None:
    with pytest.raises(NamedFileNotFoundError):
        named_file(path, folder, ())


def test_a_file_in_the_chats_attachments_counts(folder: Path, tmp_path: Path) -> None:
    sent = tmp_path / "attachments" / "a1"
    sent.mkdir(parents=True)
    (sent / "shot.png").write_bytes(b"png")

    assert named_file(str(sent / "shot.png"), folder, (sent,)) == (sent / "shot.png").resolve()
    with pytest.raises(NamedFileNotFoundError):
        named_file(str(sent / "shot.png"), folder, ())


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def test_the_api_serves_a_named_file_as_a_download_and_refuses_others(
    api: Api, tmp_path: Path
) -> None:
    created = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": "Do it", "mode": "in_place"}
    )
    session = created.json()
    cwd = tmp_path / "repo"
    (cwd / "page.html").write_text("<script>alert(1)</script>")
    (tmp_path / "outside.txt").write_text("no")
    url = f"/api/sessions/{session['id']}/file"

    found = await api.http.get(url, params={"path": "page.html"})
    outside = await api.http.get(url, params={"path": "../../outside.txt"})

    assert found.status_code == 200
    assert found.content == b"<script>alert(1)</script>"
    assert found.headers["content-type"] == "application/octet-stream"
    assert found.headers["content-disposition"].startswith("attachment")
    assert found.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert outside.status_code == 404
