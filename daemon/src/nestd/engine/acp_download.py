"""Fetching an engine that is published as an archive, as the ACP Registry lists it (B153).

The archive for this computer (`AcpEngine.downloads`, by the registry's platform name) is
downloaded over HTTPS into the version's hidden folder, refused unless its SHA-256 is the
pinned one, and unpacked there: no entry may land outside the folder or be a link, and
files keep the permissions the archive gives them. Like an npm install, the version
folder is moved into place only once its program is there.
"""

import asyncio
import hashlib
import shutil
import stat
import tarfile
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath

import httpx

from nestd.providers.acp_engines import AcpEngine, Download

# Downloads `url` into the file at the path; raises DownloadError or OSError.
type Downloader = Callable[[str, Path], Awaitable[None]]

DOWNLOAD_TIME_LIMIT = 900.0
# Larger than any engine published so far (about 175 MB), smaller than a full disk.
MAX_ARCHIVE_BYTES = 1_000_000_000
_ARCHIVE = ".archive"


class DownloadError(Exception):
    """The archive could not be fetched, was not the pinned one, or could not be unpacked;
    the message says why, in plain words.
    """


async def download_file(url: str, path: Path) -> None:
    if not url.startswith("https://"):
        msg = "Nest downloads engines only over HTTPS"
        raise DownloadError(msg)
    try:
        async with (
            httpx.AsyncClient(timeout=DOWNLOAD_TIME_LIMIT, follow_redirects=True) as client,
            client.stream("GET", url) as response,
        ):
            response.raise_for_status()
            size = 0
            with path.open("wb") as file:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_ARCHIVE_BYTES:
                        msg = "the download is larger than any engine should be"
                        raise DownloadError(msg)
                    file.write(chunk)
    except httpx.HTTPError as error:
        msg = f"the download failed ({type(error).__name__})"
        raise DownloadError(msg) from error


def archive_for(engine: AcpEngine, where: str) -> Download:
    found = engine.downloads.get(where)
    if found is None:
        msg = f"{engine.name} is not published for this computer ({where})"
        raise DownloadError(msg)
    return found


async def fetch_archive(engine: AcpEngine, folder: Path, download: Downloader, where: str) -> None:
    """`engine.version` into `folder/<version>/`, whole or not at all; other versions stay.
    Raises DownloadError or OSError.
    """
    version = engine.version
    assert version is not None  # noqa: S101 (a fetched engine's)
    pinned = archive_for(engine, where)
    target = folder / version
    partial = folder / f".{version}.partial"
    try:
        await asyncio.to_thread(fresh_folder, partial)
        archive = partial / _ARCHIVE
        await download(pinned.url, archive)
        await asyncio.to_thread(_check_and_unpack, archive, pinned)
        if not (partial / pinned.program).is_file():
            msg = f"{engine.name}'s program was not found in its archive"
            raise DownloadError(msg)
        await asyncio.to_thread(move_into_place, partial, target)
    except (DownloadError, OSError):
        await asyncio.to_thread(shutil.rmtree, partial, True)
        raise


def _check_and_unpack(archive: Path, pinned: Download) -> None:
    digest = hashlib.sha256()
    with archive.open("rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    if digest.hexdigest() != pinned.sha256:
        msg = "the download is not the one Nest pinned (its checksum differs)"
        raise DownloadError(msg)
    folder = archive.parent
    if pinned.url.endswith(".zip"):
        _unzip(archive, folder)
    elif pinned.url.endswith((".tar.gz", ".tgz")):
        _untar(archive, folder)
    else:
        msg = "the download is not an archive Nest unpacks"
        raise DownloadError(msg)
    archive.unlink()


def _inside(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        msg = "the archive has an entry outside its folder"
        raise DownloadError(msg)
    return path


def _unzip(archive: Path, folder: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as zipped:
            for entry in zipped.infolist():
                path = folder / _inside(entry.filename)
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    msg = "the archive has a link in it"
                    raise DownloadError(msg)
                if entry.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(entry) as source, path.open("wb") as copy:
                    shutil.copyfileobj(source, copy)
                if mode & 0o777:
                    path.chmod(mode & 0o755)
    except zipfile.BadZipFile as error:
        msg = "the archive could not be unpacked"
        raise DownloadError(msg) from error


def _untar(archive: Path, folder: Path) -> None:
    try:
        with tarfile.open(archive, "r:gz") as packed:
            for member in packed.getmembers():
                _inside(member.name)
                if member.issym() or member.islnk():
                    msg = "the archive has a link in it"
                    raise DownloadError(msg)
            packed.extractall(folder, filter="data")
    except tarfile.TarError as error:
        msg = "the archive could not be unpacked"
        raise DownloadError(msg) from error


def fresh_folder(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)


def move_into_place(partial: Path, target: Path) -> None:
    shutil.rmtree(target, ignore_errors=True)
    partial.rename(target)
