"""How well a local model can work as an agent (B106): agents call tools all the time, so a
model without tool use cannot, and a small one or a short context does it badly.
"""

import re

from nestd.local.models import ToolsRating

# Below this many billion parameters a model often calls tools wrongly.
SMALL_BELOW = 14.0
# An agent's first request alone is 15 to 23 thousand tokens (spike); below 64k Claude
# Code compacts the chat after almost every step (live check, qwen3-4b at 40k).
CONTEXT_MIN = 65536
_SIZE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)b(?![a-z])", re.IGNORECASE)


def size_in_name(name: str) -> float | None:
    """The size in billions a name such as `qwen3-8b` states; the first one counts."""
    match = _SIZE.search(name)
    return None if match is None else float(match.group(1))


def rate(
    *, name: str, params: float | None, context: int | None, tools: bool | None, app: str | None
) -> tuple[ToolsRating, str | None]:
    """The rating and, when not good, why in one sentence. `params` is the size in billions
    the server reports, `tools` whether it says the model calls tools.
    """
    if tools is False:
        return "none", "This model cannot call tools, which an agent needs."
    if context is not None and context < CONTEXT_MIN:
        where = app or "the server"
        return (
            "weak",
            f"Context of {context // 1024}k is too small for an agent: set {where} to 64k.",
        )
    size = params if params is not None else size_in_name(name)
    if size is not None and size < SMALL_BELOW:
        text = f"{size:g}"
        article = "An" if text.startswith("8") or text in ("11", "18") else "A"
        return (
            "weak",
            f"{article} {text}B model is small for an agent: it often calls tools wrongly.",
        )
    if size is None and context is None and tools is None:
        return "unknown", None
    return "good", None
