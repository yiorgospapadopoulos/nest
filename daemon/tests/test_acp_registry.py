"""The ACP Registry is read only for Nest's own engines (B153): it says where a pin lags,
and an entry Nest cannot read never passes as one it can.
"""

import json
from dataclasses import replace

import pytest

from nestd.engine.acp_registry import RegistryError, drift, parse
from nestd.providers.acp_engines import GEMINI, AcpEngine, Download

_REGISTRY = {
    "version": "1.0.0",
    "agents": [
        {
            "id": "gemini",
            "name": "Gemini CLI",
            "version": "0.66.0",
            "distribution": {"npx": {"package": "@google/gemini-cli@0.66.0", "args": ["--acp"]}},
        },
        {
            "id": "shipped",
            "name": "Shipped",
            "version": "2.0.0",
            "distribution": {
                "binary": {
                    "darwin-aarch64": {
                        "archive": "https://example.com/shipped-2.0.0.zip",
                        "cmd": "./shipped",
                        "sha256": "b" * 64,
                    }
                }
            },
        },
    ],
}
SHIPPED = AcpEngine(
    id="shipped",
    name="Shipped",
    package=None,
    version="1.0.0",
    executable="shipped",
    args=(),
    delivery="download",
    sign_in="terminal",
    tested=True,
    git_guard=True,
    registry_id="shipped",
    downloads={"darwin-aarch64": Download("https://example.com/shipped-1.0.0.zip", "a" * 64, "x")},
)


def test_a_pin_that_matches_its_entry_is_not_reported() -> None:
    pinned = replace(GEMINI, version="0.66.0")

    assert drift((pinned,), parse(json.dumps(_REGISTRY).encode()), "darwin-aarch64") == []


def test_a_newer_archive_is_reported_with_its_checksum() -> None:
    [found] = drift((SHIPPED,), parse(json.dumps(_REGISTRY).encode()), "darwin-aarch64")

    assert (found.pinned, found.listed) == ("1.0.0", "2.0.0")
    assert "shipped-2.0.0.zip" in found.note
    assert "b" * 64 in found.note


def test_an_archive_without_a_checksum_is_not_one_nest_takes() -> None:
    body = json.loads(json.dumps(_REGISTRY))
    del body["agents"][1]["distribution"]["binary"]["darwin-aarch64"]["sha256"]

    [found] = drift((SHIPPED,), parse(json.dumps(body).encode()), "darwin-aarch64")

    assert found.note == "the registry has no checked archive for darwin-aarch64"


def test_a_renamed_package_and_a_missing_entry_are_reported() -> None:
    renamed = replace(GEMINI, package="@google/old-cli", version="0.66.0")
    gone = replace(SHIPPED, registry_id="gone")

    found = drift((renamed, gone), parse(json.dumps(_REGISTRY).encode()), "darwin-aarch64")

    assert [item.note for item in found] == [
        "the registry names the package @google/gemini-cli",
        "not in the registry",
    ]


def test_an_answer_nest_cannot_read_is_an_error() -> None:
    with pytest.raises(RegistryError):
        parse(b'{"agents": [{"id": "x"}]}')
