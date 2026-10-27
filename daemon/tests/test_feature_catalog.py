"""B103: the catalog of what Nest can do, read from the TOML file shipped with the daemon."""

from datetime import date
from pathlib import Path

import pytest

from nestd.features.catalog import (
    CatalogError,
    load_catalog,
    packaged_catalog,
)

GROUPS = """
[[groups]]
id = "around"
name = "Getting around"

[[groups]]
id = "git"
name = "Worktrees and git"
"""

FEATURES = """
[[features]]
id = "needs-you"
group = "around"
name = "Needs you"
text = "Everything waiting on you in one list."
where = "Right panel"
added = 2026-10-17
block = "B77"

[[features]]
id = "feedback-to-agent"
group = "git"
name = "Feedback back to the agent"
text = "Failed checks go to the chat with `one click`."
where = "Needs you"
added = 2026-10-14
changed = 2026-10-21
block = "B101"
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "catalog.toml"
    path.write_text(text, encoding="utf-8")
    return path


def failure(tmp_path: Path, text: str) -> str:
    path = write(tmp_path, text)
    with pytest.raises(CatalogError) as raised:
        load_catalog(path)
    message = str(raised.value)
    assert message.startswith(f"{path}: ")
    return message


def test_a_valid_catalog_keeps_groups_and_features_in_file_order(tmp_path: Path) -> None:
    catalog = load_catalog(write(tmp_path, GROUPS + FEATURES))

    assert [(g.id, g.name) for g in catalog.groups] == [
        ("around", "Getting around"),
        ("git", "Worktrees and git"),
    ]
    first, second = catalog.features
    assert (first.id, first.group, first.added, first.changed, first.block) == (
        "needs-you",
        "around",
        date(2026, 10, 17),
        None,
        "B77",
    )
    assert second.changed == date(2026, 10, 21)
    assert second.text == "Failed checks go to the chat with `one click`."
    assert second.where == "Needs you"


def test_the_shipped_catalog_loads_and_is_cached() -> None:
    catalog = packaged_catalog()

    assert catalog is packaged_catalog()
    assert catalog.groups[0].id == "around"
    assert len(catalog.features) > len(catalog.groups)
    assert {f.group for f in catalog.features} == {g.id for g in catalog.groups}


def test_a_missing_file_is_named(tmp_path: Path) -> None:
    path = tmp_path / "absent.toml"

    with pytest.raises(CatalogError, match=r"absent\.toml: not found"):
        load_catalog(path)


def test_invalid_toml_is_reported(tmp_path: Path) -> None:
    assert "invalid TOML" in failure(tmp_path, "[[groups]\n")


def test_feature_ids_are_unique(tmp_path: Path) -> None:
    text = GROUPS + FEATURES.replace('id = "feedback-to-agent"', 'id = "needs-you"')

    assert failure(tmp_path, text).endswith('feature id "needs-you" is used more than once')


def test_group_ids_are_unique(tmp_path: Path) -> None:
    text = GROUPS + '\n[[groups]]\nid = "around"\nname = "Again"\n' + FEATURES

    assert failure(tmp_path, text).endswith('group id "around" is used more than once')


def test_every_feature_names_an_existing_group(tmp_path: Path) -> None:
    text = GROUPS + FEATURES.replace('group = "git"', 'group = "gits"')

    # Every problem is listed, here the group left without features too.
    assert failure(tmp_path, text).endswith(
        'feature "feedback-to-agent" names an unknown group "gits"; group "git" has no features'
    )
