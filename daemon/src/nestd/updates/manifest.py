"""What a prepared environment holds, in `<env>/nest-engines.json`.

The ACP engine list applies it when it loads (`providers/acp_engines.py`), from the
environment this process runs in, so an engine's version moves with the environment on a
swap or a rollback, and the base, which has no manifest, keeps the versions in the code.
"""

from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ValidationError

MANIFEST_NAME = "nest-engines.json"


class Manifest(BaseModel):
    # The base environment this one was made from; only that base may run it.
    base_fingerprint: str
    # Engine id to the package version the environment has: for an ACP engine, the folder
    # under `<data_dir>/engines/<id>/`.
    packages: Mapping[str, str]
    # Engine id to the version people see; for Claude that is Claude Code's, not the SDK's.
    shown: Mapping[str, str] = {}
    # What the update brings, as words for the notice of a rollback.
    summary: str = ""


def read_manifest(environment: Path) -> Manifest | None:
    """None when the folder has no readable manifest, as in the base."""
    try:
        return Manifest.model_validate_json((environment / MANIFEST_NAME).read_bytes())
    except (OSError, ValidationError):
        return None


def write_manifest(environment: Path, manifest: Manifest) -> None:
    (environment / MANIFEST_NAME).write_text(manifest.model_dump_json(), encoding="utf-8")
