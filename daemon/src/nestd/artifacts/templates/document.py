"""Documents: long Markdown read like a report, with contents from its `##` and `###` headings
(a sticky column on wide frames, a collapsible block on narrow ones) and editing in place:
each `##` section, and the part before the first, can be edited and saved through the
bridge's `saveDocument` as a new version based on this one. The source stays in an escaped
`<pre>`, readable without scripts.
"""

import re
from collections.abc import Mapping
from html import escape

from nestd.artifacts.templates.shared import diagrams, libraries, page, resource, script, source

# The Markdown starts with its own level 1 heading, so the page shows no title of its own.
_OWN_TITLE = re.compile(r"(?:[ \t]*\r?\n)*[ ]{0,3}#(?:[ \t\r\n]|$)")


def render(title: str, content: str, version: int, init: Mapping[str, object] | None) -> str:
    heading = "" if _OWN_TITLE.match(content) else f'<h1 class="doc-title">{escape(title)}</h1>\n'
    body = (
        f'<div id="nest-doc" class="doc-layout nest-pending" data-version="{int(version)}">\n'
        '<nav id="nest-toc-side" class="toc-side" aria-label="Contents" hidden></nav>\n'
        f'<main class="doc">\n{heading}'
        '<details id="nest-toc-top" class="toc-top" hidden><summary>Contents</summary>'
        '<nav aria-label="Contents"></nav></details>\n'
        f'{source("nest-md", content)}\n<div id="nest-sections" class="prose"></div>\n'
        "</main>\n</div>"
    )
    return page(
        title=title,
        init=init,
        css=resource("document.css"),
        body=body,
        code=script(
            diagrams(), resource("common.js"), resource("markdown.js"), resource("document.js")
        ),
        libraries=libraries(3),
        loading=True,
    )
