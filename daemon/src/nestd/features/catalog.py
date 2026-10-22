"""Read and validate the feature catalog, `catalog.toml` next to this module."""

import tomllib
from collections import Counter
from datetime import date
from functools import cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, ValidationError

PACKAGED = files("nestd.features") / "catalog.toml"


class CatalogError(Exception):
    """The catalog file is missing or breaks one of its rules."""


def _not_empty(value: str) -> str:
    if not value.strip():
        msg = "must not be empty"
        raise ValueError(msg)
    return value


type Id = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
type Text = Annotated[str, AfterValidator(_not_empty)]


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class Group(_Strict):
    id: Id
    name: Text


class Feature(_Strict):
    id: Id
    group: str
    name: Text
    # Plain sentences; `backticks` spans show as inline code.
    text: Text
    where: Text
    added: date
    block: Annotated[str, StringConstraints(pattern=r"^B[0-9]+$")]
    # Shows the feature as new again from this day.
    changed: date | None = None

    @property
    def day(self) -> date:
        """The day the feature counts from: when it last changed, else when it was added."""
        return self.changed or self.added


class Catalog(_Strict):
    groups: list[Group]
    features: list[Feature]

    def problems(self) -> list[str]:
        """The rules across entries that the fields alone do not check."""
        found = [
            f'{kind} id "{value}" is used more than once'
            for kind, ids in (
                ("group", [g.id for g in self.groups]),
                ("feature", [f.id for f in self.features]),
            )
            for value, count in Counter(ids).items()
            if count > 1
        ]
        group_ids = {g.id for g in self.groups}
        used = {f.group for f in self.features}
        for feature in self.features:
            if feature.group not in group_ids:
                found.append(f'feature "{feature.id}" names an unknown group "{feature.group}"')
            if feature.changed is not None and feature.changed < feature.added:
                found.append(
                    f'feature "{feature.id}" is changed ({feature.changed}) before it was'
                    f" added ({feature.added})"
                )
        found.extend(f'group "{g.id}" has no features' for g in self.groups if g.id not in used)
        return found

    @classmethod
    def checked(cls, data: object, source: str) -> Self:
        try:
            catalog = cls.model_validate(data)
        except ValidationError as error:
            problems = "; ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in error.errors()
            )
            msg = f"{source}: {problems}"
            raise CatalogError(msg) from error
        if problems := catalog.problems():
            msg = f"{source}: {'; '.join(problems)}"
            raise CatalogError(msg)
        return catalog


def load_catalog(source: Traversable) -> Catalog:
    """Read a catalog file; CatalogError names the file and every problem found."""
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        msg = f"{source}: not found"
        raise CatalogError(msg) from error
    except tomllib.TOMLDecodeError as error:
        msg = f"{source}: invalid TOML: {error}"
        raise CatalogError(msg) from error
    return Catalog.checked(data, str(source))


@cache
def packaged_catalog() -> Catalog:
    """The catalog shipped with the daemon, read once."""
    return load_catalog(PACKAGED)
