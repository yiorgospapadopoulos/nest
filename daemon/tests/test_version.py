import tomllib
from pathlib import Path

import nestd

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_matches_project_metadata() -> None:
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]

    assert nestd.__version__ == declared
