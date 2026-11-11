"""The newest published version of a package, from PyPI's JSON API and npm's registry."""

from typing import cast

import httpx

from nestd.updates.pypi import PYPI_URL, newest_in

# npm's `latest` dist-tag; scoped names work unescaped in this path.
_NPM = "https://registry.npmjs.org/{package}/latest"


class RegistryError(Exception):
    """A registry could not be asked or answered something else."""


async def _json(client: httpx.AsyncClient, url: str) -> dict[str, object]:
    try:
        response = await client.get(url)
        response.raise_for_status()
        body: object = response.json()
    except (httpx.HTTPError, ValueError) as error:
        msg = f"{url}: {type(error).__name__}"
        raise RegistryError(msg) from error
    if not isinstance(body, dict):
        msg = f"{url}: not an object"
        raise RegistryError(msg)
    return cast("dict[str, object]", body)


async def latest_on_pypi(client: httpx.AsyncClient, package: str) -> str | None:
    """None when the newest release was pulled."""
    body = await _json(client, PYPI_URL.format(package=package))
    try:
        return newest_in(body, package)
    except ValueError as error:
        raise RegistryError(str(error)) from error


async def latest_on_npm(client: httpx.AsyncClient, package: str) -> str:
    version = (await _json(client, _NPM.format(package=package))).get("version")
    if not isinstance(version, str):
        msg = f"npm's answer for {package} has no version"
        raise RegistryError(msg)
    return version
