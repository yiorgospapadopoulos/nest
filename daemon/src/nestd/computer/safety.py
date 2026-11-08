"""What computer use never does, and what it asks the user before doing (B150, D178).

Best effort by design: labels are what apps show, so the agent is also told to mark
anything consequential itself, and that marking always asks.
"""

import re

from nestd.computer.models import Action, Element

# Words in a button or menu item that mean the action leaves the user's hands.
_RISKY = re.compile(
    r"\b(send|submit|buy|purchase|pay|order|checkout|check out|delete|remove|erase|trash"
    r"|publish|post|transfer|confirm|empty)\b",
    re.IGNORECASE,
)
# Labels of secret fields, beside the secure role apps give password fields.
_SECRET = re.compile(
    r"password|passcode|passphrase|card number|cvv|cvc|security code|expiry|expiration"
    r"|iban|account number",
    re.IGNORECASE,
)
# Apps where every action changes settings.
SETTINGS_APPS = frozenset({"mac:com.apple.systempreferences", "mac:com.apple.Settings"})
_SEND_KEYS = frozenset({"return", "enter"})


def is_secret(element: Element) -> bool:
    return element.secure or bool(_SECRET.search(element.label))


def risk(target: str, action: Action, element: Element | None, consequential: bool) -> str | None:
    """Why this action must be asked first, in plain words, or None when it may go ahead."""
    if consequential:
        return "The agent marked this action as one to check first."
    if target in SETTINGS_APPS:
        return "It changes a setting."
    if action.kind == "menu":
        risky = next((item for item in action.menu if _RISKY.search(item)), None)
        return f'It chooses "{risky}".' if risky else None
    if action.kind in ("press", "click") and element is not None:
        match = _RISKY.search(element.label)
        return f'It presses "{element.label}".' if match else None
    if action.kind == "key" and (action.key or "").lower() in _SEND_KEYS:
        if _plain(element):
            return "Return in this field may send or submit it."
        if "cmd" in action.modifiers:
            return "Cmd-Return usually sends."
    if action.kind == "type" and (action.text or "").endswith(("\n", "\r")) and _plain(element):
        return "The text ends with Return, which may send or submit the field."
    return None


def _plain(element: Element | None) -> bool:
    """A single-line field that is not an address or search field."""
    return element is not None and element.field and not element.address
