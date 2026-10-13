import pytest

from harness.pixies.errors import InvalidSlugError
from harness.pixies.slugs import check_slug, slugify


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Tester", "tester"),
        ("Release Manager!", "release-manager"),
        ("  --Ünïcode  name-- ", "unicode-name"),
        ("!!!", "pixie"),
        ("x" * 40, "x" * 32),
    ],
)
def test_slugify(name: str, slug: str) -> None:
    assert slugify(name) == slug


@pytest.mark.parametrize(
    "slug", ["", "Tester", "-a", "a_b", "a" * 33, "plan", "explore", "general-purpose"]
)
def test_bad_slugs_are_refused(slug: str) -> None:
    with pytest.raises(InvalidSlugError):
        check_slug(slug)


def test_good_slug_passes() -> None:
    check_slug("tester-2")
