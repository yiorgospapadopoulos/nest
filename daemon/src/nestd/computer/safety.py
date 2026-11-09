"""What computer use never does (B150, D178): type into password or payment fields. The
chat's Allow for an app covers everything else in it (D178, 2026-11-09)."""

import re

from nestd.computer.models import Element

# Labels of secret fields, beside the secure role apps give password fields.
_SECRET = re.compile(
    r"password|passcode|passphrase|card number|cvv|cvc|security code|expiry|expiration"
    r"|iban|account number",
    re.IGNORECASE,
)


def is_secret(element: Element) -> bool:
    return element.secure or bool(_SECRET.search(element.label))
