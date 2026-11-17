"""`release/make_manifest.py` lists each download twice, with and without the version. The
installer and updates take the first `app` for a platform, so the copy for the fixed
download link must never be one.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

RELEASE = Path(__file__).resolve().parents[2] / "release"


def _load() -> ModuleType:
    sys.path.insert(0, str(RELEASE))
    try:
        spec = importlib.util.spec_from_file_location("make_manifest", RELEASE / "make_manifest.py")
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(RELEASE))


@pytest.mark.parametrize(
    ("name", "listed"),
    [
        ("Nest-0.1.1-macos-arm64.zip", ("app", "macos-arm64")),
        ("Nest-macos-arm64.zip", ("latest-app", "macos-arm64")),
        ("Nest-0.1.1-linux-x86_64.AppImage", ("app", "linux-x86_64")),
        ("Nest-linux-arm64.AppImage", ("latest-app", "linux-arm64")),
        ("Nest-0.1.1-linux-arm64.deb", ("deb", "linux-arm64")),
        ("Nest-linux-x86_64.deb", ("latest-deb", "linux-x86_64")),
    ],
)
def test_the_fixed_name_copies_are_never_taken_for_the_app(
    name: str, listed: tuple[str, str]
) -> None:
    assert _load().kind_of(name) == listed
