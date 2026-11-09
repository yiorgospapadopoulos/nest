"""An engine published as an archive (B153) is installed only when its download is the
pinned one, and nothing in it may land outside its folder.
"""

import asyncio
import hashlib
import io
import stat
import tarfile
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from nestd.engine.acp_download import DownloadError, fetch_archive
from nestd.engine.acp_install import EngineInstall, installed_program
from nestd.engine.acp_registry import platform_name
from nestd.providers.acp_engines import ANTIGRAVITY, AcpEngine, Download


def zipped(entries: dict[str, tuple[bytes, int]]) -> bytes:
    """A zip of name to (content, mode)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, (content, mode) in entries.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            archive.writestr(info, content)
    return buffer.getvalue()


class Served:
    """A download that serves fixed bytes."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.urls: list[str] = []

    async def __call__(self, url: str, path: Path) -> None:
        self.urls.append(url)
        await asyncio.to_thread(path.write_bytes, self.body)


def engine_for(body: bytes, url: str = "https://example.com/agy.zip") -> Download:
    return Download(url, hashlib.sha256(body).hexdigest(), "agy_acp_server.par")


def pinned(download: Download) -> AcpEngine:
    return replace(ANTIGRAVITY, downloads={platform_name(): download})


async def test_the_pinned_archive_installs_with_its_program_runnable(tmp_path: Path) -> None:
    body = zipped({"agy_acp_server.par": (b"#!/bin/sh\n", 0o100755), "lib/x": (b"x", 0o100644)})
    served = Served(body)
    engine = pinned(engine_for(body))
    install = EngineInstall(
        engine, tmp_path / "engines", _no_npm, _env, tmp_path / "home", download=served
    )

    state = await install.install()

    assert state.state == "ready"
    program = installed_program(engine, tmp_path / "engines" / "antigravity" / "1.4.5")
    assert program is not None
    assert program.stat().st_mode & stat.S_IXUSR
    assert not (tmp_path / "engines" / "antigravity" / "1.4.5" / ".archive").exists()
    assert served.urls == ["https://example.com/agy.zip"]


async def test_a_download_that_is_not_the_pinned_one_is_refused(tmp_path: Path) -> None:
    body = zipped({"agy_acp_server.par": (b"#!/bin/sh\n", 0o100755)})
    engine = pinned(replace(engine_for(body), sha256="0" * 64))
    install = EngineInstall(
        engine, tmp_path / "engines", _no_npm, _env, tmp_path / "home", download=Served(body)
    )

    state = await install.install()

    assert state.state == "install_failed"
    assert state.detail is not None
    assert "checksum" in state.detail
    assert list((tmp_path / "engines" / "antigravity").iterdir()) == []


@pytest.mark.parametrize(
    "entries",
    [
        {"../outside": (b"x", 0o100644), "agy_acp_server.par": (b"x", 0o100755)},
        {"/etc/outside": (b"x", 0o100644), "agy_acp_server.par": (b"x", 0o100755)},
        {"agy_acp_server.par": (b"/bin/sh", 0o120777)},
    ],
)
async def test_an_entry_outside_the_folder_or_a_link_is_refused(
    tmp_path: Path, entries: dict[str, tuple[bytes, int]]
) -> None:
    body = zipped(entries)

    with pytest.raises(DownloadError):
        await fetch_archive(pinned(engine_for(body)), tmp_path, Served(body), platform_name())

    assert left(tmp_path) == []
    assert "outside" not in left(tmp_path.parent)


async def test_a_tar_with_a_link_is_refused(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        link = tarfile.TarInfo("agy_acp_server.par")
        link.type = tarfile.SYMTYPE
        link.linkname = "/bin/sh"
        archive.addfile(link)
    body = buffer.getvalue()
    download = engine_for(body, "https://example.com/agy.tar.gz")

    with pytest.raises(DownloadError):
        await fetch_archive(pinned(download), tmp_path, Served(body), platform_name())

    assert left(tmp_path) == []


async def test_a_computer_the_engine_is_not_published_for_says_so(tmp_path: Path) -> None:
    engine = replace(ANTIGRAVITY, downloads={})

    with pytest.raises(DownloadError, match="not published for this computer"):
        await fetch_archive(engine, tmp_path, Served(b""), platform_name())


def left(folder: Path) -> list[str]:
    return sorted(entry.name for entry in folder.iterdir())


async def _no_npm(*_args: object) -> None:
    raise AssertionError


async def _env() -> dict[str, str]:
    return {"PATH": "/nowhere"}
