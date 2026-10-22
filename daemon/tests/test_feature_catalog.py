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


def test_unknown_top_level_keys_are_refused(tmp_path: Path) -> None:
    assert "extra: Extra inputs are not permitted" in failure(
        tmp_path, "extra = 1\n" + GROUPS + FEATURES
    )


def test_unknown_feature_keys_are_refused(tmp_path: Path) -> None:
    text = GROUPS + FEATURES.replace('block = "B77"', 'block = "B77"\ncolour = "red"')

    assert "features.0.colour: Extra inputs are not permitted" in failure(tmp_path, text)


def test_unknown_group_keys_are_refused(tmp_path: Path) -> None:
    text = GROUPS.replace('name = "Getting around"', 'name = "Getting around"\nicon = "x"')

    assert "groups.0.icon: Extra inputs are not permitted" in failure(tmp_path, text + FEATURES)


def test_missing_fields_are_refused(tmp_path: Path) -> None:
    text = GROUPS + FEATURES.replace('where = "Right panel"\n', "")

    assert "features.0.where: Field required" in failure(tmp_path, text)


@pytest.mark.parametrize("field", ["name", "text", "where"])
def test_empty_texts_are_refused(tmp_path: Path, field: str) -> None:
    lines = [
        f'{field} = "  "' if line.startswith(f"{field} = ") else line
        for line in FEATURES.splitlines()
    ]

    assert f"features.0.{field}: Value error, must not be empty" in failure(
        tmp_path, GROUPS + "\n".join(lines)
    )


def test_an_empty_group_name_is_refused(tmp_path: Path) -> None:
    text = GROUPS.replace('"Getting around"', '""')

    assert "groups.0.name: Value error, must not be empty" in failure(tmp_path, text + FEATURES)


def test_texts_must_be_strings(tmp_path: Path) -> None:
    text = GROUPS + FEATURES.replace('name = "Needs you"', "name = 3")

    assert "features.0.name: Input should be a valid string" in failure(tmp_path, text)


def test_dates_must_be_plain_dates(tmp_path: Path) -> None:
    text = GROUPS + FEATURES.replace("added = 2026-10-17", "added = 2026-10-17T09:00:00")

    assert "features.0.added: Input should be a valid date" in failure(tmp_path, text)


def test_a_quoted_date_is_refused(tmp_path: Path) -> None:
    text = GROUPS + FEATURES.replace("added = 2026-10-17", 'added = "2026-10-17"')

    assert "features.0.added: Input should be a valid date" in failure(tmp_path, text)


@pytest.mark.parametrize("bad", ["Needs-you", "needs--you", "-needs", "needs_you", ""])
def test_feature_ids_are_kebab_case(tmp_path: Path, bad: str) -> None:
    text = GROUPS + FEATURES.replace('id = "needs-you"', f'id = "{bad}"')

    assert "features.0.id: String should match pattern" in failure(tmp_path, text)


def test_group_ids_are_kebab_case(tmp_path: Path) -> None:
    text = GROUPS.replace('id = "git"', 'id = "Git"') + FEATURES.replace(
        'group = "git"', 'group = "Git"'
    )

    assert "groups.1.id: String should match pattern" in failure(tmp_path, text)


@pytest.mark.parametrize("bad", ["77", "b77", "B", "B7a"])
def test_blocks_are_b_and_digits(tmp_path: Path, bad: str) -> None:
    text = GROUPS + FEATURES.replace('block = "B77"', f'block = "{bad}"')

    assert "features.0.block: String should match pattern" in failure(tmp_path, text)


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


def test_every_group_has_a_feature(tmp_path: Path) -> None:
    text = GROUPS + FEATURES.replace('group = "git"', 'group = "around"')

    assert failure(tmp_path, text).endswith('group "git" has no features')


def test_changed_is_not_before_added(tmp_path: Path) -> None:
    text = GROUPS + FEATURES.replace("changed = 2026-10-21", "changed = 2026-10-13")

    assert failure(tmp_path, text).endswith(
        'feature "feedback-to-agent" is changed (2026-10-13) before it was added (2026-10-14)'
    )


def test_changed_on_the_day_it_was_added_is_allowed(tmp_path: Path) -> None:
    text = GROUPS + FEATURES.replace("changed = 2026-10-21", "changed = 2026-10-14")

    assert load_catalog(write(tmp_path, text)).features[1].changed == date(2026, 10, 14)


def test_a_catalog_without_groups_or_features_is_refused(tmp_path: Path) -> None:
    message = failure(tmp_path, "")

    assert "groups: Field required" in message
    assert "features: Field required" in message
