"""Nest's artifact pages built from the agent's data (B88): Markdown, slides, documents,
designs and design systems, so agents never write their HTML.
"""

from collections.abc import Mapping
from typing import Literal

from nestd.artifacts.templates import design, design_system, document, markdown, slides

type TemplateKind = Literal["markdown", "slides", "document", "design", "design_system"]
TEMPLATE_KINDS: tuple[TemplateKind, ...] = (
    "markdown",
    "slides",
    "document",
    "design",
    "design_system",
)


def render(
    kind: str,
    title: str,
    content: str,
    version: int,
    init: Mapping[str, object] | None = None,
) -> str:
    """The page of a version of an artifact built from its data. A document sends its
    `version` as `base_version` when the user saves an edit; the other kinds ignore it.
    `init` is the page's initial data for the shim (what it stored; B88 stage 3).
    """
    match kind:
        case "markdown":
            return markdown.render(title, content, init)
        case "slides":
            return slides.render(title, content, init)
        case "document":
            return document.render(title, content, version, init)
        case "design":
            return design.render(title, content, init)
        case "design_system":
            return design_system.render(title, content, init)
        case _:
            msg = f"no template for artifact kind {kind!r}"
            raise ValueError(msg)
