"""The ACP Registry, read for the engines Nest supports only (B153, D182).

The registry (agentclientprotocol.com) is a public list of agents that speak ACP, each with
where its vendor publishes it: an npm package, or an archive per platform with its
checksum. Nest never offers an agent from it that it has not added and tested itself: each
of its engines names its entry (`AcpEngine.registry_id`), and the pinned version, package
and archives in `acp_engines` come from there. `nestd engines registry` shows where the
registry has moved past the pins.
"""

import platform
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ValidationError

from nestd.providers.acp_engines import AcpEngine

REGISTRY_URL = "https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"
REGISTRY_TIME_LIMIT = 30.0
# The registry's platform names.
_OS = {"darwin": "darwin", "linux": "linux"}
_ARCH = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64", "amd64": "x86_64"}


class RegistryError(Exception):
    """The registry could not be read, or answered something else."""


class Npx(BaseModel):
    # `<name>@<version>`.
    package: str
    args: list[str] = []


class Archive(BaseModel):
    archive: str
    cmd: str
    args: list[str] = []
    sha256: str | None = None


class Distribution(BaseModel):
    npx: Npx | None = None
    binary: dict[str, Archive] = {}


class Entry(BaseModel):
    id: str
    name: str
    version: str
    distribution: Distribution


class _Registry(BaseModel):
    agents: list[Entry]


def platform_name() -> str:
    """This machine as the registry names platforms, such as `darwin-aarch64`."""
    machine = platform.machine()
    return f"{_OS.get(sys.platform, sys.platform)}-{_ARCH.get(machine, machine)}"


def parse(body: bytes) -> dict[str, Entry]:
    """The registry's entries by id; an entry Nest cannot read is left out."""
    try:
        return {entry.id: entry for entry in _Registry.model_validate_json(body).agents}
    except ValidationError as error:
        msg = f"the registry's answer is not one Nest reads ({error.error_count()} problems)"
        raise RegistryError(msg) from error


async def fetch(client: httpx.AsyncClient) -> dict[str, Entry]:
    try:
        response = await client.get(REGISTRY_URL)
        response.raise_for_status()
    except httpx.HTTPError as error:
        msg = f"the registry could not be read: {type(error).__name__}"
        raise RegistryError(msg) from error
    return parse(response.content)


@dataclass(frozen=True)
class Drift:
    """Where an engine's pin and its registry entry differ, in plain words."""

    engine: str
    pinned: str | None
    listed: str | None
    note: str


def drift(engines: Sequence[AcpEngine], entries: Mapping[str, Entry], where: str) -> list[Drift]:
    """Each engine whose registry entry differs from what Nest pins, on platform `where`."""
    found: list[Drift] = []
    for engine in engines:
        if engine.registry_id is None:
            continue
        entry = entries.get(engine.registry_id)
        if entry is None:
            found.append(Drift(engine.name, engine.version, None, "not in the registry"))
            continue
        note = _difference(engine, entry, where)
        if note is not None:
            found.append(Drift(engine.name, engine.version, entry.version, note))
    return found


def _difference(engine: AcpEngine, entry: Entry, where: str) -> str | None:
    npx, archive = entry.distribution.npx, entry.distribution.binary.get(where)
    if engine.delivery == "bundled" and npx is not None:
        package = npx.package.rsplit("@", 1)[0]
        if package != engine.package:
            return f"the registry names the package {package}"
    if engine.delivery == "download":
        if archive is None or archive.sha256 is None:
            return f"the registry has no checked archive for {where}"
        pinned = engine.downloads.get(where)
        if pinned is None or pinned.sha256 != archive.sha256:
            return f"newer archive: {archive.archive} sha256 {archive.sha256}"
    if engine.version is not None and engine.version != entry.version:
        return "a newer version is listed"
    return None
