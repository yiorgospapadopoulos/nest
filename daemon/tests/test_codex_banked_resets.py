"""B98 round 2: Codex's banked resets. Each account's available count comes with every
read of its windows; the credits themselves only with a detailed read, and one is used
with Codex's own `account/rateLimitResetCredit/consume`. The app-server is the fake.
"""

from datetime import UTC, datetime

import pytest
from pydantic import JsonValue

from nestd.providers.base import BankedCredit, BankedResets
from nestd.providers.codex_engine import fetch_codex_usage
from nestd.providers.codex_limits import banked_resets
from nestd.providers.codex_process import CodexLaunch
from nestd.providers.codex_rpc import JsonObject
from nestd.storage.db import Database
from nestd.usage.store import UsageStore
from tests.codex_support import RATE_LIMITS, FakeAppServer
from tests.fakes import FakeClock

LAUNCH = CodexLaunch(("codex", "app-server", "--listen", "stdio://"), {})
CREDIT: JsonObject = {
    "id": "credit-1",
    "title": "Weekly reset",
    "description": "Resets your Codex limits",
    "expiresAt": 1767225600,
    "grantedAt": 1764547200,
    "resetType": "codexRateLimits",
    "status": "available",
}
USED: JsonObject = {**CREDIT, "id": "credit-0", "status": "redeemed"}


def with_credits(count: int, details: list[JsonObject] | None) -> JsonObject:
    summary: JsonObject = {
        "availableCount": count,
        "credits": None if details is None else list[JsonValue](details),
    }
    return {**RATE_LIMITS, "rateLimitResetCredits": summary}


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({}, None),
        ({"rateLimitResetCredits": None}, None),
        ({"rateLimitResetCredits": {"availableCount": 2}}, BankedResets(available=2)),
        (
            {"rateLimitResetCredits": {"availableCount": 1, "credits": [CREDIT, USED]}},
            BankedResets(
                available=1,
                credits=[
                    BankedCredit(
                        id="credit-1",
                        title="Weekly reset",
                        description="Resets your Codex limits",
                        expires_at=datetime(2026, 1, 1, tzinfo=UTC),
                    )
                ],
            ),
        ),
        (
            {
                "rateLimitResetCredits": {
                    "availableCount": 1,
                    "credits": [{"id": "c", "status": "available"}, {"status": "available"}],
                }
            },
            BankedResets(
                available=1,
                credits=[BankedCredit(id="c", title=None, description=None, expires_at=None)],
            ),
        ),
        ({"rateLimitResetCredits": {"credits": []}}, BankedResets(available=0, credits=[])),
    ],
)
def test_the_banked_resets_codex_reports_are_read(
    response: JsonObject, expected: BankedResets | None
) -> None:
    assert banked_resets(response) == expected


async def test_a_scheduled_read_keeps_the_count_without_the_details() -> None:
    server = FakeAppServer()
    server.answers["account/rateLimits/read"] = with_credits(3, None)

    usage = await fetch_codex_usage(server, LAUNCH)

    assert usage is not None
    assert usage.banked == BankedResets(available=3)
    assert server.requests("account/rateLimits/read") == [{"excludeResetCreditDetails": True}]
    # Never in the usage events' payloads.
    assert "banked" not in usage.model_dump()


async def test_the_store_keeps_each_accounts_count_and_its_last_details(
    db: Database, clock: FakeClock
) -> None:
    usage = UsageStore(db, clock)
    credit = BankedCredit(id="c", title=None, description=None, expires_at=None)
    read = await fetch_codex_usage(FakeAppServer(), LAUNCH)
    assert read is not None
    info = read.model_copy(update={"banked": BankedResets(available=1, credits=[credit])})
    await usage.update_limits(info, "abcdefabcdef")
    same = info.model_copy(update={"banked": BankedResets(available=1)})
    await usage.update_limits(same, "abcdefabcdef")
    kept = await usage.banked("abcdefabcdef")
    fewer = info.model_copy(update={"banked": BankedResets(available=0)})
    await usage.update_limits(fewer, "abcdefabcdef")
    await usage.update_limits(info.model_copy(update={"banked": None}), "abcdefabcdef")

    assert kept == BankedResets(available=1, credits=[credit])
    assert await usage.banked("abcdefabcdef") == BankedResets(available=0)
    assert await usage.banked("codex-main") is None
    await usage.forget("abcdefabcdef")
    assert await usage.banked("abcdefabcdef") is None
