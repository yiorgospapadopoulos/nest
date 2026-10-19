"""Slides: Markdown split into slides on lines that are exactly `---`, each laid out on a
1280 by 720 stage scaled to fit the frame and letterboxed, so a slide never scrolls and its
text never reflows by device. Keys, swipes and taps on the outer thirds move between slides;
printing gives one slide per landscape page. The source stays in an escaped `<pre>`, readable
without scripts; without marked each slide shows its Markdown as text.
"""

from collections.abc import Mapping

from nestd.artifacts.templates.shared import diagrams, libraries, page, resource, script, source

_DECK = (
    '<main id="nest-deck" class="deck nest-pending" aria-label="Slides"'
    ' aria-roledescription="slide deck">'
    '<div id="nest-stage" class="stage"></div></main>'
)
_CHROME = (
    '<div class="chrome nest-pending"><div class="progress"><span id="nest-progress"></span></div>'
    '<output id="nest-count" class="count" aria-live="polite"></output></div>'
)


def render(title: str, content: str, init: Mapping[str, object] | None) -> str:
    return page(
        title=title,
        init=init,
        css=resource("slides.css"),
        body=f"{_DECK}\n{source('nest-md', content)}\n{_CHROME}",
        code=script(
            diagrams(), resource("common.js"), resource("markdown.js"), resource("slides.js")
        ),
        libraries=libraries(3),
        loading=True,
    )
