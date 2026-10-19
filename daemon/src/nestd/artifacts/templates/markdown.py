"""Plain Markdown (B82; built here since B88 stage 3): the source in an escaped `<pre>`, then
rendered with the pinned marked, Mermaid and highlight.js, cleaned like every kind's agent
Markdown, with diagrams drawn once the frame is shown. Nothing shows before it is rendered;
when the libraries fail, the source shows as it is.
"""

from collections.abc import Mapping

from nestd.artifacts.templates.shared import diagrams, libraries, page, resource, script, source


def render(title: str, content: str, init: Mapping[str, object] | None) -> str:
    return page(
        title=title,
        init=init,
        css=resource("markdown_page.css"),
        body=source("nest-md", content),
        code=script(
            diagrams(),
            resource("common.js"),
            resource("markdown.js"),
            resource("markdown_page.js"),
        ),
        libraries=libraries(3),
        loading=True,
    )
