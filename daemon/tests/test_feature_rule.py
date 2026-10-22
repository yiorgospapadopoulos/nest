"""B103: when a feature shows as new on a device."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from nestd.features.catalog import Feature
from nestd.features.rule import new_ids

ATHENS = ZoneInfo("Europe/Athens")
# 2026-10-21 in UTC and in Athens.
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def feature(fid: str, added: date, changed: date | None = None) -> Feature:
    return Feature(
        id=fid,
        group="around",
        name=fid,
        text="Text.",
        where="Here",
        added=added,
        block="B1",
        changed=changed,
    )


def test_before_the_first_visit_today_is_the_first_visit() -> None:
    features = [
        feature("today", date(2026, 10, 21)),
        feature("yesterday", date(2026, 10, 20)),
        feature("two-days-ago", date(2026, 10, 19)),
    ]

    assert new_ids(features, None, {}, NOW, UTC) == {"today", "yesterday"}


def test_the_day_before_the_first_visit_counts_but_not_the_one_before() -> None:
    visit = datetime(2026, 10, 10, 8, 0, tzinfo=UTC)
    features = [
        feature("day-before", date(2026, 10, 9)),
        feature("two-days-before", date(2026, 10, 8)),
        feature("later", date(2026, 10, 15)),
    ]

    assert new_ids(features, visit, {}, NOW, UTC) == {"day-before", "later"}


def test_a_changed_date_wins_over_the_added_date() -> None:
    visit = datetime(2026, 10, 10, 8, 0, tzinfo=UTC)
    features = [
        feature("changed-later", date(2026, 9, 1), changed=date(2026, 10, 12)),
        feature("changed-long-ago", date(2026, 9, 1), changed=date(2026, 9, 2)),
    ]

    assert new_ids(features, visit, {}, NOW, UTC) == {"changed-later"}


def test_a_shown_feature_is_no_longer_new_right_away() -> None:
    features = [feature("shown", date(2026, 10, 21)), feature("not-shown", date(2026, 10, 21))]

    assert new_ids(features, NOW, {"shown"}, NOW, UTC) == {"not-shown"}


def test_a_shown_feature_that_is_not_a_candidate_is_not_new() -> None:
    features = [feature("old", date(2026, 1, 1))]

    assert new_ids(features, NOW, {"old"}, NOW, UTC) == set()


def test_the_first_visit_day_is_read_in_the_daemons_calendar() -> None:
    # 01:30 on 2026-10-21 in Athens, still 2026-10-20 in UTC.
    visit = datetime(2026, 10, 20, 22, 30, tzinfo=UTC)
    features = [feature("f", date(2026, 10, 19))]

    assert new_ids(features, visit, {}, NOW, UTC) == {"f"}
    assert new_ids(features, visit, {}, NOW, ATHENS) == set()


def test_without_a_zone_the_systems_calendar_is_used() -> None:
    visit = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    local_day = visit.astimezone().date()
    features = [feature("f", local_day - timedelta(days=1))]

    assert new_ids(features, visit, {}, NOW, None) == {"f"}
