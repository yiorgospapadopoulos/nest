"""When a feature shows as new on a device (B103).

A feature is a candidate when its day is on or after the day before the device's first
visit, in the daemon's calendar; before the first visit is recorded, today counts as it.
A candidate is new until the device first shows it.
"""

from collections.abc import Collection, Iterable
from datetime import datetime, timedelta, tzinfo

from nestd.features.catalog import Feature


def new_ids(
    features: Iterable[Feature],
    first_visit: datetime | None,
    shown: Collection[str],
    now: datetime,
    zone: tzinfo | None,
) -> set[str]:
    """The ids of the new features. `shown` holds the ids the device has shown; `zone` is
    the calendar's time zone, None the system's.
    """
    since = (first_visit or now).astimezone(zone).date() - timedelta(days=1)
    return {feature.id for feature in features if feature.day >= since and feature.id not in shown}
