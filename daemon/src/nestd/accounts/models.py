"""The accounts as Settings > Accounts lists them (B98)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from nestd.providers.base import BankedResets
from nestd.usage.models import AccountWindow

type AccountProvider = Literal["claude", "codex"]
NAME_LIMIT = 40


class Account(BaseModel):
    id: str
    provider: str
    # The user's own name for it.
    name: str | None
    # The name, else the email, else the engine's name.
    title: str
    email: str | None
    # As the engine names the plan, such as "Claude Max" or "ChatGPT Plus".
    plan: str | None
    # None when the engine could not be asked.
    signed_in: bool | None
    # The account the engine's turns run on; exactly one per engine.
    active: bool
    # The user's own login, never removable.
    first: bool
    signing_in: bool
    # Why the last sign in failed, or why the engine could not be asked.
    error: str | None
    limits: list[AccountWindow]
    checked_at: datetime | None
    # Codex's banked resets (B98); None for Claude, which has none, and before Codex said.
    banked_resets: BankedResets | None


class AccountList(BaseModel):
    """`GET /api/accounts` and the `accounts.changed` event: Claude's, then Codex's."""

    accounts: list[Account]


class AccountSignIn(BaseModel):
    account: Account
    # Codex's sign-in page, which the client opens; None for Claude, whose sign in opens
    # the browser on the Mac itself.
    auth_url: str | None


type ResetOutcome = Literal["reset", "nothing_to_reset", "no_credit", "already_redeemed"]


class BankedResetUse(BaseModel):
    credit_id: str


class BankedResetUsed(BaseModel):
    """`POST /api/accounts/{id}/banked-resets/use`: what Codex did, and the accounts after."""

    outcome: ResetOutcome
    accounts: list[Account]


class AccountName(BaseModel):
    name: str | None

    @field_validator("name")
    @classmethod
    def trimmed(cls, name: str | None) -> str | None:
        """Trimmed; empty clears it."""
        if name is None or not name.strip():
            return None
        if len(name.strip()) > NAME_LIMIT:
            msg = f"a name has at most {NAME_LIMIT} characters"
            raise ValueError(msg)
        return name.strip()
