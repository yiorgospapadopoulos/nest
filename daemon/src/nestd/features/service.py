"""The catalog as a device sees it: grouped, with what is new on that device (B103)."""

from datetime import date, tzinfo

from pydantic import BaseModel

from nestd.clock import Clock
from nestd.features.catalog import Catalog
from nestd.features.rule import new_ids
from nestd.features.store import FeatureStore


class FeatureView(BaseModel):
    id: str
    name: str
    text: str
    where: str
    added: date
    changed: date | None
    block: str
    new: bool


class GroupView(BaseModel):
    id: str
    name: str
    features: list[FeatureView]


class FeaturesView(BaseModel):
    groups: list[GroupView]
    new_count: int


class Features:
    def __init__(
        self, store: FeatureStore, clock: Clock, zone: tzinfo | None, catalog: Catalog
    ) -> None:
        """`zone` is the calendar that decides which day the first visit falls on; None is
        the system's time zone."""
        self._store = store
        self._clock = clock
        self._zone = zone
        self._catalog = catalog

    async def view(self, device_id: str) -> FeaturesView:
        state = await self._store.state(device_id)
        new = new_ids(
            self._catalog.features, state.first_visit, state.shown, self._clock.now(), self._zone
        )
        groups = [
            GroupView(
                id=group.id,
                name=group.name,
                features=[
                    FeatureView(
                        id=f.id,
                        name=f.name,
                        text=f.text,
                        where=f.where,
                        added=f.added,
                        changed=f.changed,
                        block=f.block,
                        new=f.id in new,
                    )
                    for f in self._catalog.features
                    if f.group == group.id
                ],
            )
            for group in self._catalog.groups
        ]
        return FeaturesView(groups=groups, new_count=len(new))

    async def mark_shown(self, device_id: str, ids: list[str]) -> FeaturesView:
        """The device shows these features; ids not in the catalog are ignored."""
        known = {f.id for f in self._catalog.features}
        await self._store.record_shown(device_id, [i for i in dict.fromkeys(ids) if i in known])
        return await self.view(device_id)
