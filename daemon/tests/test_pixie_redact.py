import pytest

from harness.pixies.redact import redact


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-abcdefghijklmnopqrstuv",
        "sk-abcdefghijklmnopqrstuvwxyz123456",
        "ghp_abcdefghijklmnopqrstuvwxyz0123",
        "github_pat_11ABCDEFG0123456789_abcdefghij",
        "AKIAABCDEFGHIJKLMNOP",
        "xoxb-1234567890-abcdefghij",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    ],
)
def test_tokens_are_redacted(secret: str) -> None:
    assert redact(f"key is {secret} ok") == "key is [redacted] ok"


def test_url_passwords_and_private_keys_are_redacted() -> None:
    key = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"

    assert redact("db at postgres://me:hunter2@host/db") == "db at postgres://[redacted]@host/db"
    assert redact(f"key {key} end") == "key [redacted] end"


def test_plain_text_is_unchanged() -> None:
    assert redact("prefers squash merges, uses sk- prefixes in docs") == (
        "prefers squash merges, uses sk- prefixes in docs"
    )
