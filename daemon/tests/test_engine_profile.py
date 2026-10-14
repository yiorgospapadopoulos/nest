import json
import logging
from pathlib import Path

import pytest

from nestd.engine.profile import profile_name

OTHER_DETAIL = "another-private-account-detail"


def _write(home: Path, data: object) -> Path:
    path = home / ".claude.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_the_display_name_is_read_from_the_oauth_account(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "oauthAccount": {
                "displayName": "Sam",
                "fullName": "Sam Rivera",
                "emailAddress": "person@example.com",
            },
            "otherField": OTHER_DETAIL,
        },
    )

    assert profile_name(path) == "Sam"


@pytest.mark.parametrize("display_name", [None, "", "   ", 42, ["Sam"]])
def test_the_full_name_is_the_fallback(tmp_path: Path, display_name: object) -> None:
    account: dict[str, object] = {"fullName": "Sam Rivera"}
    if display_name is not None:
        account["displayName"] = display_name
    path = _write(tmp_path, {"oauthAccount": account})

    assert profile_name(path) == "Sam Rivera"


def test_surrounding_whitespace_is_trimmed(tmp_path: Path) -> None:
    path = _write(tmp_path, {"oauthAccount": {"displayName": "  Sam \n"}})

    assert profile_name(path) == "Sam"


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"oauthAccount": None},
        {"oauthAccount": "Sam"},
        {"oauthAccount": {}},
        {"oauthAccount": {"displayName": " ", "fullName": ""}},
        {"oauthAccount": {"displayName": 1, "fullName": False}},
        ["oauthAccount"],
        "Sam",
    ],
)
def test_no_usable_name_gives_none(tmp_path: Path, data: object) -> None:
    assert profile_name(_write(tmp_path, data)) is None


def test_no_path_or_a_missing_file_gives_none_without_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        assert profile_name(None) is None
        assert profile_name(tmp_path / ".claude.json") is None

    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_bad_json_is_logged_by_kind_without_the_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / ".claude.json"
    path.write_text('{"otherField": "' + OTHER_DETAIL + '", "oauthAccount": {', encoding="utf-8")

    with caplog.at_level(logging.DEBUG):
        assert profile_name(path) is None

    assert "JSONDecodeError" in caplog.text
    assert OTHER_DETAIL not in caplog.text
    assert "otherField" not in caplog.text


def test_an_unreadable_file_is_logged_by_kind(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / ".claude.json"
    path.mkdir()

    with caplog.at_level(logging.WARNING):
        assert profile_name(path) is None

    assert "IsADirectoryError" in caplog.text


def test_invalid_utf8_is_logged_by_kind(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / ".claude.json"
    path.write_bytes(b'{"oauthAccount": {"displayName": "\xff"}}')

    with caplog.at_level(logging.WARNING):
        assert profile_name(path) is None

    assert "UnicodeDecodeError" in caplog.text


def test_the_file_is_never_changed(tmp_path: Path) -> None:
    path = _write(tmp_path, {"oauthAccount": {"displayName": "Sam"}, "other": [1, 2]})
    before = path.read_bytes(), path.stat().st_mtime_ns

    profile_name(path)

    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
