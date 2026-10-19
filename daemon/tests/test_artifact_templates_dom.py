"""The templates' scripts run in jsdom (the web part's test DOM, `web/node_modules`; skipped
when node or jsdom is missing): slides split and navigate, document sections split, edit and
rebuild the Markdown for `saveDocument`, and design screens and components are sandboxed in
shadow roots with `:root` rewritten and scripts stripped. Libraries from the CDN do not load
here; a small stand-in for marked is given where rendering matters.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nestd.artifacts import templates
from nestd.artifacts.kinds import slides_of
from nestd.design.loader import find_root

_JSDOM = find_root(Path(__file__).resolve()) / "web" / "node_modules" / "jsdom"

# Loads a page in jsdom with optional stand-ins (marked; the Mac's reply handler with queued
# replies), runs a scenario module on it and prints what the scenario returns, with the
# page's script errors.
_HARNESS = r"""
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [pagePath, jsdomPath, optionsText, scenarioPath] = process.argv.slice(2);
const require = createRequire(jsdomPath + "/");
const { JSDOM, VirtualConsole } = require(jsdomPath);
const options = JSON.parse(optionsText);
const errors = [];
const requests = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", (error) => errors.push(String(error.message || error)));

function escape(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
// Headings, fenced code through the renderer, raw HTML blocks passed through as marked does,
// and paragraphs: enough of marked for the tests.
function fakeMarked() {
  return {
    Renderer: function () {},
    parse(text, settings) {
      const out = [];
      const lines = text.replace(/\r/g, "").split("\n");
      let block = [];
      const flush = () => {
        if (block.length) out.push("<p>" + escape(block.join(" ")) + "</p>");
        block = [];
      };
      for (let at = 0; at < lines.length; at += 1) {
        const line = lines[at];
        const fence = /^```(.*)$/.exec(line);
        const heading = /^(#{1,6})\s+(.*)$/.exec(line);
        if (fence) {
          flush();
          const code = [];
          for (at += 1; at < lines.length && !/^```/.test(lines[at]); at += 1) code.push(lines[at]);
          out.push(settings.renderer.code(code.join("\n"), fence[1]));
        } else if (line.startsWith("<")) {
          flush();
          const html = [line];
          while (at + 1 < lines.length && lines[at + 1].trim() !== "") html.push(lines[(at += 1)]);
          out.push(html.join("\n"));
        } else if (heading) {
          flush();
          const level = heading[1].length;
          out.push("<h" + level + ">" + escape(heading[2]) + "</h" + level + ">");
        } else if (line.trim() === "") {
          flush();
        } else {
          block.push(line);
        }
      }
      flush();
      return out.join("\n");
    },
  };
}

// Mermaid as far as the templates use it: it measures on screen, so a frame that is not
// rendered (window.__width 0, as jsdom's layout always is) gives the empty 16 by 16 diagram.
// Every element's box is window.__width wide.
function fakeMermaid(window, settings) {
  window.__width = settings.width || 0;
  window.Element.prototype.getBoundingClientRect = function () {
    const width = window.__width;
    return { width, height: width ? 543 : 0, left: 0, top: 0, right: width, bottom: 0, x: 0, y: 0 };
  };
  window.mermaid = {
    calls: [],
    initialize(config) { this.config = config; },
    run({ nodes }) {
      const deck = window.document.getElementById("nest-deck");
      const call = { sources: [], deck: deck ? deck.style.opacity : null,
        stage: deck ? window.document.getElementById("nest-stage").style.transform : null };
      this.calls.push(call);
      const empty = settings.empty === "always" || (settings.empty === "first" && this.calls.length === 1)
        || (settings.empty === "blind" && this.blind !== false);
      for (const node of nodes) {
        if (node.getAttribute("data-processed")) continue;
        node.setAttribute("data-processed", "true");
        call.sources.push(node.textContent);
        const size = window.__width && !empty ? "300 100" : "16 16";
        node.innerHTML = '<svg viewBox="-8 -8 ' + size + '"></svg>';
      }
      return new Promise((resolve) => setTimeout(resolve, 0));
    },
  };
}

const dom = new JSDOM(readFileSync(pagePath, "utf8"), {
  runScripts: "dangerously",
  pretendToBeVisual: true,
  virtualConsole,
  beforeParse(window) {
    if (options.marked) window.marked = fakeMarked();
    if (options.matchMedia) window.matchMedia = () => ({ matches: false });
    if (options.brokenMarked) {
      window.marked = { Renderer: function () {}, parse() { throw new Error("broken"); } };
    }
    // jsdom has no blob URLs: each call gives a new one naming the blob's type and size.
    let blobs = 0;
    window.URL.createObjectURL = (blob) => "blob:nest/" + (blobs += 1) + "/" + blob.type + "/" + blob.size;
    // Seconds-long timers (the libraries' fallback) run at once.
    if (options.fastTimers) {
      const wait = window.setTimeout;
      window.setTimeout = (fn, ms, ...rest) => wait(fn, ms >= 1000 ? 10 : ms, ...rest);
    }
    if (options.breakScript) {
      Object.defineProperty(window, "ResizeObserver", { get() { throw new Error("broken"); } });
    }
    if (options.mermaid) fakeMermaid(window, options.mermaid);
    if (options.replies) {
      window.webkit = { messageHandlers: { nest: { postMessage(request) {
        requests.push(JSON.parse(JSON.stringify(request)));
        const reply = options.replies.shift() || { ok: true, result: {} };
        return new Promise((resolve) => setTimeout(() => resolve({ nest: 1, id: request.id, ...reply }), 0));
      } } } };
    }
  },
});
// A click or key press as the user's own (isTrusted), which a page's script cannot make.
const idl = require(jsdomPath + "/lib/generated/idl/utils.js");
function trusted(target, type = "click", init = {}) {
  const Event = type.startsWith("key") ? dom.window.KeyboardEvent : dom.window.MouseEvent;
  const event = new Event(type, { bubbles: true, cancelable: true, composed: true, ...init });
  idl.implForWrapper(event).isTrusted = true;
  idl.implForWrapper(target)._dispatch(idl.implForWrapper(event));
  return event;
}
const { default: scenario } = await import(pathToFileURL(scenarioPath).href);
const tick = () => new Promise((resolve) => setTimeout(resolve, 5));
const result = await scenario({ window: dom.window, document: dom.window.document, requests, tick, trusted });
console.log(JSON.stringify({ result, errors }));
process.exit(0);
"""  # noqa: E501 (embedded JavaScript)


def run_page(
    tmp_path: Path,
    page: str,
    scenario: str,
    *,
    marked: bool = False,
    replies: list[dict[str, Any]] | None = None,
    mermaid: dict[str, Any] | None = None,
    extra: dict[str, bool] | None = None,
) -> Any:  # noqa: ANN401 (what the scenario returns, as JSON)
    node = shutil.which("node")
    if node is None or not _JSDOM.is_dir():
        pytest.skip("node or the web part's jsdom (npm ci in web/) is not installed")
    (tmp_path / "harness.mjs").write_text(_HARNESS, encoding="utf-8")
    (tmp_path / "page.html").write_text(page, encoding="utf-8")
    (tmp_path / "scenario.mjs").write_text(
        "export default async function ({ window, document, requests, tick, trusted }) {\n"
        + scenario
        + "\n}",
        encoding="utf-8",
    )
    options: dict[str, Any] = {"marked": marked, "mermaid": mermaid, **(extra or {})}
    if replies is not None:
        options["replies"] = replies
    done = subprocess.run(  # noqa: S603
        [
            node,
            str(tmp_path / "harness.mjs"),
            str(tmp_path / "page.html"),
            str(_JSDOM),
            json.dumps(options),
            str(tmp_path / "scenario.mjs"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    # Lines end with "\n" only: splitlines would also split at U+2028 inside the JSON.
    output = json.loads(done.stdout.strip().split("\n")[-1])
    assert output["errors"] == []
    return output["result"]


# Slides.

_KEYS = """
const key = (name, extra = {}) =>
  document.dispatchEvent(new window.KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true, ...extra }));
const count = () => document.getElementById("nest-count").textContent;
"""  # noqa: E501 (embedded JavaScript)


def test_slides_split_on_lines_that_are_exactly_three_dashes(tmp_path: Path) -> None:
    deck = "# One\r\n---\r\nTwo\n--- \nstill two\n ---\nstill\n---\n\n---\n   \n---\nThree\n---"
    result = run_page(
        tmp_path,
        templates.render("slides", "Deck", deck, 1),
        """
        return {
          ready: document.body.classList.contains("ready"),
          slides: [...document.querySelectorAll(".slide")].map((slide) => slide.textContent),
          labels: [...document.querySelectorAll(".slide")].map((slide) => slide.getAttribute("aria-label")),
          count: document.getElementById("nest-count").textContent,
          progress: document.getElementById("nest-progress").style.width,
          current: [...document.querySelectorAll(".slide")].map((slide) => slide.classList.contains("current")),
        };
        """,  # noqa: E501 (embedded JavaScript)
    )

    assert result == {
        "ready": True,
        # Without marked each slide shows its Markdown as text (the parser reads CR LF as LF).
        "slides": ["# One", "Two\n--- \nstill two\n ---\nstill", "Three"],
        "labels": ["1 of 3", "2 of 3", "3 of 3"],
        "count": "1 / 3",
        "progress": "33.33333333333333%",
        "current": [True, False, False],
    }


@pytest.mark.parametrize(
    "deck",
    [
        "A\n---\nB",
        "A\r\n---\r\nB\r\n---\r\nC",
        "A\n--- \nB\n ---\nC\n----\nD\n-- -\nE\n---\nF",
        "```\ncode\n---\nmore\n```",
        "# T\n\nSetext\n---\nnext",
    ],
)
def test_the_deck_splits_exactly_as_the_daemon_checks_it(tmp_path: Path, deck: str) -> None:
    result = run_page(
        tmp_path,
        templates.render("slides", "Deck", deck, 1),
        'return [...document.querySelectorAll(".slide")].map((slide) => slide.textContent);',
    )

    # The page's parser reads CR LF as LF; otherwise the slides are the daemon's.
    assert result == [slide.replace("\r", "") for slide in slides_of(deck)]


def test_a_deck_of_nothing_still_has_one_slide(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("slides", "Deck", "---\n\n---", 1),
        """
        const count = document.getElementById("nest-count").textContent;
        return [document.querySelectorAll(".slide").length, count];
        """,
    )

    assert result == [1, "1 / 1"]


def test_slides_move_with_keys_and_never_touch_the_url(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("slides", "Deck", "A\n---\nB\n---\nC\n---\nD", 1),
        _KEYS
        + """
        const seen = [];
        for (const [name, extra] of [
          ["ArrowRight"], ["ArrowDown"], ["ArrowRight"], ["PageDown"], ["ArrowLeft"], ["ArrowUp"],
          ["PageUp"], ["PageUp"], [" "], [" ", { shiftKey: true }], ["End"], ["Home"],
          ["ArrowRight", { metaKey: true }], ["ArrowRight", { ctrlKey: true }], ["constructor"],
        ]) {
          key(name, extra);
          seen.push(count());
        }
        const field = document.createElement("textarea");
        document.body.appendChild(field);
        field.dispatchEvent(new window.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
        seen.push(count());
        return { seen, hash: window.location.hash, hidden: document.querySelector(".slide:not(.current)").getAttribute("aria-hidden") };
        """,  # noqa: E501 (embedded JavaScript)
    )

    assert result == {
        "seen": [
            "2 / 4",
            "3 / 4",
            "4 / 4",
            "4 / 4",
            "3 / 4",
            "2 / 4",
            "1 / 4",
            "1 / 4",
            "2 / 4",
            "1 / 4",
            "4 / 4",
            "1 / 4",
            "1 / 4",
            "1 / 4",
            "1 / 4",
            "1 / 4",
        ],
        "hash": "",
        "hidden": "true",
    }


def test_slides_move_with_taps_on_the_outer_thirds_and_swipes(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("slides", "Deck", "A\n---\nB\n---\nC", 1),
        _KEYS
        + """
        const deck = document.getElementById("nest-deck");
        const click = (x) => deck.dispatchEvent(new window.MouseEvent("click", { clientX: x, bubbles: true, cancelable: true }));
        const pointer = (type, x, y, id = 1, pointerType = "touch") =>
          deck.dispatchEvent(new window.PointerEvent(type, { clientX: x, clientY: y, pointerId: id, pointerType, bubbles: true }));
        const seen = [];
        // The frame is 1024 wide here: the right third goes forward, the left back.
        click(900); seen.push(count());
        click(500); seen.push(count());
        click(100); seen.push(count());
        // A swipe left goes forward; the click after it does nothing more.
        pointer("pointerdown", 600, 300); pointer("pointerup", 400, 310); click(400); seen.push(count());
        // Too short, or mostly vertical: no swipe.
        pointer("pointerdown", 600, 300); pointer("pointerup", 580, 300); seen.push(count());
        pointer("pointerdown", 600, 300); pointer("pointerup", 500, 500); seen.push(count());
        // A swipe right goes back.
        pointer("pointerdown", 300, 300); pointer("pointerup", 500, 300); seen.push(count());
        // Two fingers are a pinch, not a swipe.
        pointer("pointerdown", 300, 300, 1); pointer("pointerdown", 400, 300, 2);
        pointer("pointerup", 800, 300, 2); pointer("pointerup", 900, 300, 1); seen.push(count());
        pointer("pointerdown", 300, 300); pointer("pointercancel", 300, 300); pointer("pointerup", 900, 300); seen.push(count());
        // A mouse drag is not a swipe.
        pointer("pointerdown", 900, 300, 3, "mouse"); pointer("pointerup", 100, 300, 3, "mouse"); seen.push(count());
        // Links are not navigation taps.
        const link = document.createElement("a");
        link.href = "https://example.com/";
        document.querySelector(".slide.current .slide-body").appendChild(link);
        link.dispatchEvent(new window.MouseEvent("click", { clientX: 900, bubbles: true, cancelable: true }));
        seen.push(count());
        return seen;
        """,  # noqa: E501 (embedded JavaScript)
    )

    assert result == [
        "2 / 3",
        "2 / 3",
        "1 / 3",
        "2 / 3",
        "2 / 3",
        "2 / 3",
        "1 / 3",
        "1 / 3",
        "1 / 3",
        "1 / 3",
        "1 / 3",
    ]


def test_slides_render_markdown_and_find_title_slides(tmp_path: Path) -> None:
    deck = "# Talk\n\nBy me\n---\n## Plan\n\nOne\n\n```js\nlet x = 1 < 2;\n```\n---\nNo heading"
    result = run_page(
        tmp_path,
        templates.render("slides", "Deck", deck, 1),
        """
        return [...document.querySelectorAll(".slide")].map((slide) => [
          slide.classList.contains("is-title"), slide.querySelector(".slide-body").innerHTML,
        ]);
        """,
        marked=True,
    )

    assert result == [
        [True, "<h1>Talk</h1>\n<p>By me</p>"],
        [False, "<h2>Plan</h2>\n<p>One</p>\n<pre><code>let x = 1 &lt; 2;</code></pre>"],
        [False, "<p>No heading</p>"],
    ]


# Document.

_DOC = (
    "# Report\n\nOpening.\n\n## First\n\nOne.\n\n```sh\n## not a section\n```\n\n"
    "### Detail\n\nMore.\n\n## First\n\nAgain.\n\n## Last\nEnd.\n"
)
_SECTIONS = """
const sections = () => [...document.querySelectorAll(".nest-section")];
const edits = () => [...document.querySelectorAll(".nest-edit")];
const toc = (id) => [...document.querySelectorAll("#" + id + " a")].map((a) => [a.getAttribute("href"), a.textContent, a.parentNode.className]);
"""  # noqa: E501 (embedded JavaScript)


def test_a_document_is_split_into_sections_with_contents(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("document", "Report", _DOC, 3),
        _SECTIONS
        + """
        return {
          sections: sections().map((section) => section.getAttribute("data-index")),
          headings: [...document.querySelectorAll("#nest-sections h1, #nest-sections h2, #nest-sections h3")].map((h) => h.id),
          side: toc("nest-toc-side"),
          top: toc("nest-toc-top"),
          shown: [document.getElementById("nest-toc-side").hidden, document.getElementById("nest-toc-top").hidden,
            document.getElementById("nest-doc").classList.contains("has-toc")],
          edits: edits().map((button) => button.getAttribute("aria-label")),
        };
        """,  # noqa: E501 (embedded JavaScript)
        marked=True,
        replies=[],
    )

    assert result == {
        "sections": ["0", "1", "2", "3"],
        "headings": ["report", "first", "detail", "first-2", "last"],
        "side": [
            ["#first", "First", "toc-2"],
            ["#detail", "Detail", "toc-3"],
            ["#first-2", "First", "toc-2"],
            ["#last", "Last", "toc-2"],
        ],
        "top": [
            ["#first", "First", "toc-2"],
            ["#detail", "Detail", "toc-3"],
            ["#first-2", "First", "toc-2"],
            ["#last", "Last", "toc-2"],
        ],
        "shown": [False, False, True],
        "edits": [
            "Edit the opening",
            "Edit section First",
            "Edit section First",
            "Edit section Last",
        ],
    }


def test_document_slugs_are_unique_and_avoid_the_pages_own_ids(tmp_path: Path) -> None:
    doc = "## Nest md\n\n## Café & crème!\n\n## ???\n\n## ???\n"
    result = run_page(
        tmp_path,
        templates.render("document", "D", doc, 1),
        'return [...document.querySelectorAll("#nest-sections h2")].map((h) => h.id);',
        marked=True,
    )

    assert result == ["nest-md-2", "café-crème", "section", "section-2"]


def test_without_marked_sections_stay_text_with_contents_from_their_headings(
    tmp_path: Path,
) -> None:
    doc = "Opening\n\n## One ##\n\nx\n\n## Two\n\ny"
    result = run_page(
        tmp_path,
        templates.render("document", "D", doc, 1),
        _SECTIONS
        + """
        return {
          raw: sections().map((section) => section.querySelector("pre.raw").textContent),
          ids: sections().map((section) => section.id),
          side: toc("nest-toc-side"),
        };
        """,
    )

    assert result == {
        "raw": ["Opening\n", "## One ##\n\nx\n", "## Two\n\ny"],
        "ids": ["", "one", "two"],
        "side": [["#one", "One", "toc-2"], ["#two", "Two", "toc-2"]],
    }


def test_a_short_document_has_no_contents(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("document", "D", "\n\n## Only\n\ntext", 1),
        _SECTIONS
        + """
        return [sections().map((s) => s.getAttribute("data-index")), document.getElementById("nest-toc-side").hidden,
          document.getElementById("nest-toc-top").hidden, document.getElementById("nest-doc").classList.contains("has-toc")];
        """,  # noqa: E501 (embedded JavaScript)
        marked=True,
    )

    # The blank part before the first heading is kept in the Markdown but not shown.
    assert result == [["1"], True, True, False]


_EDIT = (
    _SECTIONS
    + """
const open = (index) => edits()[index].click();
const area = () => document.querySelector(".nest-editor textarea");
const button = (name) => [...document.querySelectorAll(".nest-editor button")].find((b) => b.textContent === name);
const status = () => document.querySelector(".nest-editor-status");
"""  # noqa: E501 (embedded JavaScript)
)


def test_saving_a_section_rebuilds_the_whole_markdown(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("document", "Report", _DOC, 3),
        _EDIT
        + """
        open(1);
        const before = { value: area().value, disabled: edits().map((b) => b.disabled),
          hidden: sections()[1].querySelector(".nest-section-body").hidden };
        // A second Edit while one is open does nothing.
        edits()[2].click();
        const editors = document.querySelectorAll(".nest-editor").length;
        area().value = "## First\\n\\nChanged.";
        trusted(button("Save"));
        const saving = [status().textContent, button("Save").disabled, button("Cancel").disabled];
        await tick();
        return { before, editors, saving, requests,
          after: { editors: document.querySelectorAll(".nest-editor").length, disabled: edits().map((b) => b.disabled),
            text: sections()[1].textContent } };
        """,  # noqa: E501 (embedded JavaScript)
        marked=True,
        replies=[{"ok": True, "result": {"version": 4}}],
    )

    section = "## First\n\nOne.\n\n```sh\n## not a section\n```\n\n### Detail\n\nMore.\n"
    assert result["before"] == {
        "value": section,
        "disabled": [True, True, True, True],
        "hidden": True,
    }
    assert result["editors"] == 1
    assert result["saving"] == ["Saving", True, True]
    expected = _DOC.replace(section, "## First\n\nChanged.\n")
    assert result["requests"] == [
        {
            "nest": 1,
            "id": result["requests"][0]["id"],
            "method": "saveDocument",
            "params": {"content": expected, "base_version": 3},
        }
    ]
    assert result["after"] == {
        "editors": 0,
        "disabled": [False, False, False, False],
        "text": "EditFirst\nChanged.",
    }


def test_the_next_save_is_based_on_the_saved_version(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("document", "D", "Top\n\n## A\n\na\n", 7),
        _EDIT
        + """
        open(1); area().value = "## A\\n\\nb"; trusted(button("Save")); await tick();
        open(0); area().value = "Top two"; trusted(area(), "keydown", { key: "Enter", metaKey: true });
        await tick();
        return requests.map((r) => r.params);
        """,  # noqa: E501 (embedded JavaScript)
        marked=True,
        replies=[{"ok": True, "result": {"version": 8}}, {"ok": True, "result": {}}],
    )

    # The last section keeps the edit as typed; earlier ones keep a line before the next heading.
    assert result == [
        {"content": "Top\n\n## A\n\nb", "base_version": 7},
        {"content": "Top two\n\n## A\n\nb", "base_version": 8},
    ]


def test_an_unchanged_save_or_cancel_closes_without_saving(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("document", "D", _DOC, 1),
        _EDIT
        + """
        open(2); trusted(button("Save"));
        const first = document.querySelectorAll(".nest-editor").length;
        open(3); area().value = "## Last\\nGone"; button("Cancel").click();
        return [first, document.querySelectorAll(".nest-editor").length, sections()[3].querySelector(".nest-section-body").hidden,
          requests.length, edits().every((b) => !b.disabled)];
        """,  # noqa: E501 (embedded JavaScript)
        marked=True,
        replies=[],
    )

    assert result == [0, 0, False, 0, True]


def test_a_conflict_keeps_the_text_and_asks_for_a_reload(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("document", "D", _DOC, 1),
        _EDIT
        + """
        open(3); area().value = "## Last\\nMine"; trusted(button("Save")); await tick();
        const shown = [status().textContent, status().className, button("Save").disabled, button("Cancel").disabled, area().value];
        trusted(button("Save")); await tick();
        return { shown, requests: requests.length };
        """,  # noqa: E501 (embedded JavaScript)
        marked=True,
        replies=[{"ok": False, "error": {"code": "conflict", "message": "Changed"}}],
    )

    assert result == {
        "shown": [
            "This document changed; reload to edit the latest version",
            "nest-editor-status is-error",
            True,
            False,
            "## Last\nMine",
        ],
        "requests": 1,
    }


def test_another_error_keeps_the_text_and_shows_the_message(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("document", "D", _DOC, 1),
        _EDIT
        + """
        open(3); area().value = "## Last\\nMine"; trusted(button("Save")); await tick();
        const first = [status().textContent, button("Save").disabled, area().value];
        trusted(button("Save")); await tick();
        return [first, status().textContent];
        """,
        marked=True,
        replies=[
            {"ok": False, "error": {"code": "too_large", "message": "Too big"}},
            {"ok": False},
        ],
    )

    assert result == [["Too big", False, "## Last\nMine"], "unavailable"]


def test_without_a_host_a_save_fails_quietly_with_a_message(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("document", "D", "## A\n\nx", 1),
        _EDIT
        + """
        open(0); area().value = "## A\\n\\ny"; trusted(button("Save")); await tick();
        return status().textContent;
        """,
        marked=True,
    )

    assert result == "Nest is not here"


def test_a_contents_link_at_the_top_closes_the_contents(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("document", "D", _DOC, 1),
        """
        const top = document.getElementById("nest-toc-top");
        top.open = true;
        const scrolled = [];
        window.HTMLElement.prototype.scrollIntoView = function () { scrolled.push(this.id); };
        top.querySelector("a[href='#last']").click();
        top.querySelector("summary").click();
        return [top.open, scrolled];
        """,
        marked=True,
    )

    # The shim scrolls first, then the closed contents scroll again.
    assert result == [True, ["last", "last"]]


# Design screens and design system components.

_SCREEN = (
    "<style>:root{--x:1} html body{margin:0} body.dark > main{color:red} .body{}"
    " @media (min-width: 1px){:root{--y:2}} @font-face{font-family:x}</style>"
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter">'
    '<link rel="preload" href="x"><meta http-equiv="refresh" content="0;url=https://x.example">'
    '<base href="https://x.example/"><iframe srcdoc="<b>"></iframe><object data="x"></object>'
    '<main onclick="alert(1)" ONMOUSEOVER="x()"><a href=" java\tscript:alert(2)">bad</a>'
    '<a href="https://example.com/">ok</a><img src="data:image/png;base64,AA" onerror="alert(3)">'
    '<svg><a xlink:href="javascript:alert(4)"><text>t</text></a></svg>'
    '<form action="javascript:alert(5)"><button formaction="vbscript:x">b</button></form>'
    "<script>alert(6)</script></main>"
)


def test_design_screens_are_sandboxed_in_shadow_roots(tmp_path: Path) -> None:
    content = json.dumps(
        {
            "screens": [
                {"title": "A", "device": "phone", "html": _SCREEN},
                {"title": "B", "device": "desktop", "html": "<p>plain</p>"},
            ]
        }
    )
    result = run_page(
        tmp_path,
        templates.render("design", "D", content, 1),
        """
        const frames = [...document.querySelectorAll("[data-screen]")];
        const shadow = frames[0].shadowRoot;
        const styles = [...shadow.querySelectorAll("style")].map((style) => style.textContent);
        const clicks = [...shadow.querySelectorAll("a")].map((a) => {
          const event = new window.MouseEvent("click", { bubbles: true, cancelable: true, composed: true });
          a.dispatchEvent(event);
          return event.defaultPrevented;
        });
        const other = new window.MouseEvent("click", { bubbles: true, cancelable: true, composed: true });
        shadow.querySelector("main").dispatchEvent(other);
        const submit = new window.Event("submit", { bubbles: true, cancelable: true });
        shadow.querySelector("form").dispatchEvent(submit);
        return {
          wrapped: [...shadow.children].map((node) => node.localName + "." + node.className),
          base: styles[0].includes(":host { all: initial;"),
          css: styles[1],
          gone: ["script", "iframe", "object", "meta", "base", "link[rel=preload]"].map((s) => shadow.querySelectorAll(s).length),
          kept: shadow.querySelectorAll("link[rel=stylesheet]").length,
          attributes: [...shadow.querySelectorAll("main, a, img, form, button")].map((node) =>
            node.localName + ":" + [...node.attributes].map((a) => a.name).join(",")),
          clicks, other: other.defaultPrevented, submit: submit.defaultPrevented,
          second: frames[1].shadowRoot.querySelector(".nest-body").innerHTML,
          page: document.querySelectorAll("#nest-world script, #nest-world main").length,
        };
        """,  # noqa: E501 (embedded JavaScript)
    )

    assert result == {
        "wrapped": ["style.", "div.nest-body"],
        "base": True,
        "css": (
            ":host{--x:1} :host .nest-body{margin:0} .nest-body.dark > main{color:red} .body{}"
            " @media (min-width: 1px){:host{--y:2}} @font-face{font-family:x}"
        ),
        "gone": [0, 0, 0, 0, 0, 0],
        "kept": 1,
        # The SVG link is not allowed: its text stays, the link goes.
        "attributes": [
            "main:",
            "a:",
            "a:href",
            "img:src",
            "form:",
            "button:",
        ],
        "clicks": [True, True],
        "other": False,
        "submit": True,
        "second": "<p>plain</p>",
        "page": 0,
    }


_ZOOM = """
const zoom = () => document.getElementById("nest-zoom").textContent;
const press = (name) => document.querySelector("[data-zoom='" + name + "']").click();
const canvas = document.getElementById("nest-canvas");
const world = document.getElementById("nest-world");
"""


def test_the_design_canvas_zooms_with_buttons_keys_wheel_and_gestures(tmp_path: Path) -> None:
    content = json.dumps(
        {"layout": "canvas", "screens": [{"title": "A", "html": "<p>a</p>"}], "notes": "Hi"}
    )
    result = run_page(
        tmp_path,
        templates.render("design", "D", content, 1),
        _ZOOM
        + """
        const seen = [zoom()];
        press("in"); seen.push(zoom());
        press("out"); seen.push(zoom());
        press("in"); press("fit"); seen.push(zoom());
        const key = (name, extra = {}) => document.dispatchEvent(new window.KeyboardEvent("keydown", { key: name, cancelable: true, ...extra }));
        key("+"); seen.push(zoom()); key("-"); seen.push(zoom()); key("="); key("0"); seen.push(zoom());
        key("+", { metaKey: true }); key("x"); seen.push(zoom());
        const wheel = (extra) => { const e = new window.WheelEvent("wheel", { cancelable: true, bubbles: true, ...extra }); canvas.dispatchEvent(e); return e.defaultPrevented; };
        const zoomed = wheel({ deltaY: -100, ctrlKey: true }); seen.push(zoom());
        wheel({ deltaY: 100, metaKey: true }); seen.push(zoom());
        // Trackpad pinch as WebKit gesture events; a ctrl-wheel during it is not counted twice.
        const gesture = (type, scale) => { const e = new window.Event(type, { cancelable: true }); e.scale = scale; e.clientX = 0; e.clientY = 0; canvas.dispatchEvent(e); return e.defaultPrevented; };
        const prevented = [gesture("gesturestart", 1), gesture("gesturechange", 2)];
        seen.push(zoom());
        wheel({ deltaY: -100, ctrlKey: true }); seen.push(zoom());
        prevented.push(gesture("gestureend", 2));
        gesture("gesturechange", 3); seen.push(zoom());
        // Plain wheel pans.
        press("fit");
        const panned = wheel({ deltaX: 10, deltaY: 30 });
        const lines = wheel({ deltaY: 2, deltaMode: 1 });
        return { seen, zoomed, prevented, panned, lines, transform: world.style.transform,
          notes: document.querySelector(".intro-body").innerHTML };
        """,  # noqa: E501 (embedded JavaScript)
        marked=True,
    )

    assert result == {
        "seen": [
            "100%",
            "125%",
            "100%",
            "100%",
            "125%",
            "100%",
            "100%",
            "100%",
            "165%",
            "100%",
            "200%",
            "200%",
            "200%",
        ],
        "zoomed": True,
        "prevented": [True, True, True],
        "panned": True,
        "lines": True,
        "transform": "translate(14px, -38px) scale(1)",
        "notes": '<div class="prose"><p>Hi</p></div>',
    }


def test_the_design_canvas_pans_and_pinches_with_pointers(tmp_path: Path) -> None:
    content = json.dumps({"layout": "canvas", "screens": [{"title": "A", "html": "<p>a</p>"}]})
    result = run_page(
        tmp_path,
        templates.render("design", "D", content, 1),
        _ZOOM
        + """
        const pointer = (type, id, x, y, extra = {}) => canvas.dispatchEvent(new window.PointerEvent(type,
          { pointerId: id, clientX: x, clientY: y, pointerType: "touch", bubbles: true, ...extra }));
        const seen = [];
        pointer("pointerdown", 1, 100, 100); pointer("pointermove", 1, 130, 90);
        seen.push(world.style.transform, canvas.classList.contains("is-panning"));
        pointer("pointerdown", 2, 230, 90); pointer("pointermove", 2, 330, 90);
        seen.push(zoom());
        // Gesture events during a touch pinch are left to the touches.
        const e = new window.Event("gesturestart", { cancelable: true }); canvas.dispatchEvent(e);
        const g = new window.Event("gesturechange", { cancelable: true }); g.scale = 4; canvas.dispatchEvent(g);
        seen.push(zoom());
        pointer("pointerup", 2, 330, 90); pointer("pointermove", 1, 140, 90); pointer("pointercancel", 1, 140, 90);
        seen.push(canvas.classList.contains("is-panning"));
        pointer("pointermove", 1, 500, 500); pointer("pointerup", 9, 0, 0);
        pointer("pointerdown", 5, 0, 0, { pointerType: "mouse", button: 2 }); pointer("pointermove", 5, 50, 50);
        seen.push(world.style.transform);
        return seen;
        """,  # noqa: E501 (embedded JavaScript)
    )

    assert result == [
        "translate(54px, 14px) scale(1)",
        True,
        "200%",
        "200%",
        False,
        "translate(-12px, -62px) scale(2)",
    ]


def test_a_design_system_mounts_each_component_sandboxed(tmp_path: Path) -> None:
    content = json.dumps(
        {
            "components": [
                {
                    "name": "Button",
                    "html": "<style>:root{color:red}</style>"
                    "<button onclick='x()'>Go</button><script>x()</script>",
                },
                {"name": "Odd", "html": 5},
            ]
        }
    )
    result = run_page(
        tmp_path,
        templates.render("design_system", "S", content, 1),
        """
        return [...document.querySelectorAll("[data-component]")].map((preview) =>
          preview.shadowRoot.querySelector(".nest-body").innerHTML);
        """,
    )

    assert result == ["<style>:host{color:red}</style><button>Go</button>", ""]


def test_a_preview_that_cannot_get_a_shadow_root_says_so(tmp_path: Path) -> None:
    content = json.dumps({"components": [{"name": "A", "html": "<b>x</b>"}]})
    page = templates.render("design_system", "S", content, 1).replace(
        "<body>", "<body><script>Element.prototype.attachShadow = null;</script>", 1
    )

    result = run_page(
        tmp_path,
        page,
        'return document.querySelector("[data-component]").textContent;',
    )

    assert result == "This preview could not be shown."


# Diagrams: Mermaid measures on screen, so they are drawn once the frame is rendered.

_DIAGRAMS = """
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const boxes = () => [...document.querySelectorAll("pre.mermaid svg")].map((svg) => svg.getAttribute("viewBox"));
const deck = document.getElementById("nest-deck");
const stage = document.getElementById("nest-stage");
"""  # noqa: E501 (embedded JavaScript)
_DECK = "# Flows\n---\n## One\n\n```mermaid\nflowchart LR\n  A --> B\n```\n---\nEnd"


def test_a_deck_loaded_hidden_draws_its_diagrams_once_shown(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("slides", "Deck", _DECK, 1),
        _DIAGRAMS
        + """
        await wait(60);
        const hidden = { calls: window.mermaid.calls.length, deck: deck.style.opacity, stage: stage.style.transform };
        // The app shows the frame: it now has a size (and gets no resize event).
        window.__width = 341;
        await wait(80);
        return { hidden, calls: window.mermaid.calls, boxes: boxes(), deck: deck.style.opacity,
          scaled: /scale\\(/.test(stage.style.transform), source: document.querySelector("pre.mermaid").getAttribute("data-source") };
        """,  # noqa: E501 (embedded JavaScript)
        marked=True,
        mermaid={"width": 0},
    )

    assert result == {
        # Nothing is drawn or scaled while the frame has no size; the deck waits hidden.
        "hidden": {"calls": 0, "deck": "0", "stage": ""},
        # Drawn once, on the unscaled stage, hidden.
        "calls": [{"sources": ["flowchart LR\n  A --> B"], "deck": "0", "stage": ""}],
        "boxes": ["-8 -8 300 100"],
        "deck": "",
        "scaled": True,
        "source": "flowchart LR\n  A --> B",
    }


def test_a_diagram_that_still_comes_out_empty_is_drawn_again(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("slides", "Deck", _DECK, 1),
        _DIAGRAMS
        + """
        await wait(80);
        return { calls: window.mermaid.calls.map((call) => call.sources), boxes: boxes(), deck: deck.style.opacity };
        """,  # noqa: E501 (embedded JavaScript)
        marked=True,
        mermaid={"width": 341, "empty": "first"},
    )

    assert result == {
        "calls": [["flowchart LR\n  A --> B"], ["flowchart LR\n  A --> B"]],
        "boxes": ["-8 -8 300 100"],
        "deck": "",
    }


def test_a_diagram_that_stays_empty_is_tried_three_times_then_shown(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("slides", "Deck", _DECK, 1),
        _DIAGRAMS
        + """
        await wait(120);
        return [window.mermaid.calls.length, boxes(), deck.style.opacity];
        """,
        marked=True,
        mermaid={"width": 341, "empty": "always"},
    )

    assert result == [3, ["-8 -8 16 16"], ""]


def test_a_frame_hidden_after_its_scripts_start_redraws_when_shown(tmp_path: Path) -> None:
    # Text measured while the scripts started, but Mermaid then measured nothing: the frame
    # was hidden in between. Shown later, its size changes and the diagram is drawn again.
    result = run_page(
        tmp_path,
        templates.render("slides", "Deck", _DECK, 1),
        _DIAGRAMS
        + """
        await wait(80);
        const before = [window.mermaid.calls.length, boxes(), deck.style.opacity];
        window.mermaid.blind = false;
        window.dispatchEvent(new window.Event("resize"));
        const during = [deck.style.opacity, stage.style.transform];
        await wait(80);
        window.dispatchEvent(new window.Event("resize"));
        await wait(40);
        const scaled = /scale\\(/.test(stage.style.transform);
        const last = window.mermaid.calls.at(-1).stage;
        return { before, during,
          after: [window.mermaid.calls.length, boxes(), deck.style.opacity, scaled, last] };
        """,
        marked=True,
        mermaid={"width": 341, "empty": "blind"},
    )

    assert result == {
        "before": [3, ["-8 -8 16 16"], ""],
        # Drawn again on the unscaled stage, hidden.
        "during": ["0", ""],
        # Once drawn, a later size change only lays the deck out again.
        "after": [4, ["-8 -8 300 100"], "", True, ""],
    }


def test_a_document_loaded_hidden_draws_its_diagrams_once_shown(tmp_path: Path) -> None:
    doc = "## Flow\n\n```mermaid\nflowchart LR\n  A --> B\n```\n"
    result = run_page(
        tmp_path,
        templates.render("document", "Doc", doc, 1),
        _DIAGRAMS
        + """
        await wait(60);
        const before = window.mermaid.calls.length;
        window.__width = 341;
        await wait(80);
        return [before, window.mermaid.calls.length, boxes(), window.mermaid.config.securityLevel];
        """,
        marked=True,
        mermaid={"width": 0},
    )

    assert result == [0, 1, ["-8 -8 300 100"], "strict"]


def test_a_document_redraws_a_diagram_drawn_empty_when_its_frame_is_shown(tmp_path: Path) -> None:
    doc = "## Flow\n\n```mermaid\nflowchart LR\n  A --> B\n```\n"
    result = run_page(
        tmp_path,
        templates.render("document", "Doc", doc, 1),
        _DIAGRAMS
        + """
        await wait(80);
        const before = [window.mermaid.calls.length, boxes()];
        window.mermaid.blind = false;
        window.dispatchEvent(new window.Event("resize"));
        await wait(80);
        window.dispatchEvent(new window.Event("resize"));
        await wait(40);
        return [before, window.mermaid.calls.length, boxes(),
          document.querySelector("pre.mermaid").getAttribute("data-source")];
        """,
        marked=True,
        mermaid={"width": 341, "empty": "blind"},
    )

    assert result == [[3, ["-8 -8 16 16"]], 4, ["-8 -8 300 100"], "flowchart LR\n  A --> B"]


# The agent's Markdown is cleaned by an allow-list before it joins the page, so a document or
# deck page runs only Nest's script.

_HOSTILE = "\n".join(
    [
        '<img src=x onerror="window.__ran=1"><svg onload="window.__ran=2"><circle r="5"'
        ' onclick="x()"/></svg>',
        '<math><mi xlink:href="javascript:window.__ran=3">m</mi><maction actiontype="statusline">'
        "t</maction></math>",
        "<style>@import url(https://evil.example/x.css); body { display: none }</style>",
        '<a href="  javascript:window.__ran=4">ws</a><a href="&#106;avascript:window.__ran=5">'
        'ent</a><a HREF="JaVaScRiPt:alert(6)">case</a><a href="https://example.com/">ok</a>'
        '<a href="#safe">anchor</a><a href="data:text/html,x">data</a>'
        '<a href="mailto:a@b.c">mail</a><a href="java&#x09;script:alert(1)">tab</a>',
        '<form action="https://evil.example/"><input name="q"><button'
        ' formaction="javascript:alert(7)">go</button></form>',
        '<object data="x"></object><embed src="x"><base href="https://evil.example/">'
        '<meta http-equiv="refresh" content="0;url=https://evil.example/">',
        '<iframe srcdoc="<script>parent.__ran=8</script>"></iframe><script>window.__ran=9</script>',
        '<IMG SRC="data:image/png;base64,iVBORw0KGgo=" OnError="window.__ran=10" alt="pic">',
        '<p id="nest-count" name="mermaid" style="position:fixed" Class="note">clobber</p>'
        '<input type="checkbox" checked disabled> task',
        '<details open ontoggle="window.__ran=11"><summary>more</summary>x</details>'
        "<!-- a comment --><template><script>x()</script></template>",
    ]
)
_CHECK = """
const report = (root) => {
  const all = [...root.querySelectorAll("*")];
  return {
    tags: [...new Set(all.map((node) => node.localName))].sort(),
    handlers: all.flatMap((node) => [...node.attributes].map((a) => a.name)).filter((name) => /^on/i.test(name)),
    links: [...root.querySelectorAll("a")].map((a) => [a.textContent, a.getAttribute("href")]),
    images: [...root.querySelectorAll("img")].map((img) => [img.getAttribute("src"), img.getAttribute("alt")]),
    clobber: [...root.querySelectorAll("p")].filter((p) => p.textContent === "clobber")
      .map((p) => [...p.attributes].map((a) => a.name + "=" + a.value)),
    inputs: [...root.querySelectorAll("input")].map((input) => [...input.attributes].map((a) => a.name)),
    text: root.textContent.includes("go") && root.textContent.includes("more"),
    ran: window.__ran === undefined ? null : window.__ran,
    hidden: window.getComputedStyle(document.body).display,
    count: document.getElementById("nest-count") && document.getElementById("nest-count").localName,
  };
};
"""  # noqa: E501 (embedded JavaScript)
_EXPECTED_TAGS = [
    "a",
    "circle",
    "details",
    "img",
    "input",
    "p",
    "summary",
    "svg",
]
_EXPECTED_LINKS = [
    ["ws", None],
    ["ent", None],
    ["case", None],
    ["ok", "https://example.com/"],
    ["anchor", "#safe"],
    ["data", None],
    ["mail", "mailto:a@b.c"],
    ["tab", None],
]


def _cleaned(result: dict[str, Any]) -> None:
    assert result["handlers"] == []
    assert result["links"] == _EXPECTED_LINKS
    # The bad image keeps no source; the data: image keeps its own.
    assert result["images"] == [[None, None], ["data:image/png;base64,iVBORw0KGgo=", "pic"]]
    # No page id, name or style; a class is fine.
    assert result["clobber"] == [["class=note"]]
    # Only a GFM checkbox stays an input; the button's text stays, the button goes.
    assert result["inputs"] == [["type", "checked", "disabled"]]
    assert result["text"] is True
    assert result["ran"] is None
    # The agent's style element was dropped, so the page is not hidden by it.
    assert result["hidden"] != "none"


def test_a_documents_raw_html_is_cleaned_and_its_diagrams_still_draw(tmp_path: Path) -> None:
    doc = f"## Safe\n\n{_HOSTILE}\n\n```mermaid\nflowchart LR\n  A --> B\n```\n"
    result = run_page(
        tmp_path,
        templates.render("document", "Doc", doc, 1),
        _CHECK
        + _DIAGRAMS
        + """
        await wait(80);
        const body = document.querySelector(".nest-section-body");
        return { ...report(body), boxes: boxes() };
        """,
        marked=True,
        mermaid={"width": 341},
    )

    _cleaned(result)
    # The section's own heading and diagram, besides what survived of the agent's HTML.
    assert result["tags"] == sorted({*_EXPECTED_TAGS, "h2", "pre"})
    # The agent's id="nest-count" was dropped (a document page has no element of that id).
    assert result["count"] is None
    assert result["boxes"] == ["-8 -8 300 100"]


def test_a_decks_raw_html_is_cleaned_and_its_diagrams_still_draw(tmp_path: Path) -> None:
    deck = f"# Title\n---\n## Safe\n\n{_HOSTILE}\n\n```mermaid\nflowchart LR\n  A --> B\n```\n"
    result = run_page(
        tmp_path,
        templates.render("slides", "Deck", deck, 1),
        _CHECK
        + _DIAGRAMS
        + """
        await wait(80);
        const body = document.querySelectorAll(".slide-body")[1];
        return { ...report(body), boxes: boxes() };
        """,
        marked=True,
        mermaid={"width": 341},
    )

    _cleaned(result)
    assert result["tags"] == sorted({*_EXPECTED_TAGS, "h2", "pre"})
    # The page's own counter is still the one found by its id.
    assert result["count"] == "output"
    assert result["boxes"] == ["-8 -8 300 100"]


def test_design_notes_are_cleaned_like_markdown(tmp_path: Path) -> None:
    content = json.dumps({"screens": [{"title": "A", "html": "<p>a</p>"}], "notes": _HOSTILE})
    result = run_page(
        tmp_path,
        templates.render("design", "D", content, 1),
        _CHECK + 'return report(document.querySelector(".intro-body"));',
        marked=True,
    )

    _cleaned(result)
    assert result["tags"] == sorted({*_EXPECTED_TAGS, "div"})


def test_screens_keep_forms_and_styles_but_nothing_that_runs(tmp_path: Path) -> None:
    html = (
        "<style>:root{--a:1} @import url(https://fonts.googleapis.com/x);</style>"
        '<link rel="stylesheet" href="http://fonts.googleapis.com/x">'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/y">'
        '<svg onload="x()"><a href="https://example.com/"><text>t</text></a></svg>'
        '<math><mi>m</mi></math><form action="javascript:x()" Method="post">'
        '<input type="text" name="q" placeholder="Search" OnFocus="x()" data-id="1">'
        '<button formaction="javascript:x()" style="color:red" aria-label="Go">Go</button></form>'
        '<a href=" &#106;avascript:x()">bad</a><object data="x"></object><embed src="x">'
        '<base href="https://x.example/"><meta http-equiv="refresh" content="0">'
    )
    content = json.dumps({"screens": [{"title": "A", "html": html}]})
    result = run_page(
        tmp_path,
        templates.render("design", "D", content, 1),
        """
        const body = document.querySelector("[data-screen]").shadowRoot.querySelector(".nest-body");
        return [...body.querySelectorAll("*")].map((node) =>
          node.localName + ":" + [...node.attributes].map((a) => a.name + "=" + a.value).join(","));
        """,
    )

    assert result == [
        "style:",
        "link:rel=stylesheet,href=https://fonts.googleapis.com/y",
        "svg:",
        "text:",
        "form:",
        "input:type=text,name=q,placeholder=Search,data-id=1",
        "button:style=color:red,aria-label=Go",
        "a:",
    ]


def test_a_save_without_the_users_click_is_refused(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("document", "D", "## A\n\nx", 1),
        _EDIT
        + """
        const direct = await window.nest.saveDocument({ content: "## A\\n\\ny", base_version: 1 })
          .then(() => "saved", (error) => error.code + ": " + error.message);
        open(0); area().value = "## A\\n\\ny";
        button("Save").click();
        await tick();
        const scripted = [status().textContent, button("Save").disabled, requests.length];
        trusted(button("Save"));
        await tick();
        return { direct, scripted, requests: requests.length };
        """,
        marked=True,
        replies=[{"ok": True, "result": {"version": 2}}],
    )

    assert result == {
        "direct": "bad_request: Saving needs a click on Save",
        "scripted": ["Saving needs a click on Save", False, 0],
        "requests": 1,
    }


# Loading: the page shows nothing half built, a ring when slow, the source when it fails.

_STATE = """
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const state = () => ({
  classes: [...document.documentElement.classList].sort(),
  source: document.getElementById("nest-md") ? window.getComputedStyle(document.getElementById("nest-md")).display : "gone",
  ring: window.getComputedStyle(document.querySelector(".nest-loading")).display,
});
"""  # noqa: E501 (embedded JavaScript)


@pytest.mark.parametrize(
    ("kind", "content"),
    [
        ("slides", "# A\n---\nB"),
        ("document", "# A\n\n## B\n\nC"),
        ("design", json.dumps({"screens": [{"title": "A", "html": "<p>a</p>"}], "notes": "Hi"})),
    ],
)
def test_a_rendered_page_is_ready_without_its_source_or_the_ring(
    tmp_path: Path, kind: str, content: str
) -> None:
    result = run_page(
        tmp_path,
        templates.render(kind, "T", content, 1),
        _STATE + "await wait(20); return state();",
        marked=True,
        # A frame with a size (jsdom lays nothing out).
        mermaid={"width": 341},
    )

    assert result["classes"] == ["nest-ready", "nest-started"]
    assert result["source"] in {"none", "gone"}
    assert result["ring"] == "none"


def test_a_markdown_page_is_ready_once_rendered(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("markdown", "T", "# Hello", 1),
        _STATE
        + "await wait(20);"
        + 'return { ...state(), doc: document.getElementById("nest-doc").innerHTML };',
        marked=True,
    )

    assert result == {
        "classes": ["nest-ready", "nest-started"],
        "source": "gone",
        "ring": "none",
        "doc": "<h1>Hello</h1>",
    }


def test_a_slow_page_shows_the_ring_and_not_its_source_until_ready(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("slides", "Deck", _DECK, 1),
        _STATE
        + """
        await wait(60);
        const waiting = state();
        window.__width = 341;
        await wait(80);
        return { waiting, ready: state() };
        """,
        marked=True,
        mermaid={"width": 0},
        extra={"fastTimers": True},
    )

    assert result == {
        # Diagrams wait for the frame to be shown: the source stays hidden, the ring shows,
        # and the fallback timer does not fire for a page whose script is running.
        "waiting": {"classes": ["nest-started"], "source": "none", "ring": "flex"},
        "ready": {"classes": ["nest-ready", "nest-started"], "source": "none", "ring": "none"},
    }


@pytest.mark.parametrize("kind", ["markdown", "slides", "document", "design"])
def test_libraries_that_never_let_the_script_run_fall_back_to_the_source(
    tmp_path: Path, kind: str
) -> None:
    content = json.dumps({"screens": [], "notes": "Hi"}) if kind == "design" else "# A"
    page = templates.render(kind, "T", content, 1)
    # The page's own script never runs, as when a library's script hangs.
    page = page[: page.rindex("<script>")] + "</body></html>"
    result = run_page(
        tmp_path, page, _STATE + "await wait(60); return state();", extra={"fastTimers": True}
    )

    assert result == {
        "classes": ["nest-fallback"],
        # The notes of a design are its Markdown there.
        "source": "gone" if kind == "design" else "block",
        "ring": "none",
    }


def test_a_markdown_page_without_marked_shows_its_source_at_once(tmp_path: Path) -> None:
    result = run_page(
        tmp_path, templates.render("markdown", "T", "# A", 1), _STATE + "return state();"
    )

    assert result == {
        "classes": ["nest-fallback", "nest-started"],
        "source": "block",
        "ring": "none",
    }


def test_a_markdown_page_whose_rendering_fails_shows_its_source(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("markdown", "T", "# A", 1),
        _STATE + "return state();",
        extra={"brokenMarked": True},
    )

    assert result == {
        "classes": ["nest-fallback", "nest-started"],
        "source": "block",
        "ring": "none",
    }


def test_a_template_whose_script_fails_shows_its_source(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("slides", "Deck", "# A", 1),
        _STATE + "return state();",
        marked=True,
        extra={"breakScript": True},
    )

    assert result == {
        "classes": ["nest-fallback", "nest-started"],
        "source": "block",
        "ring": "none",
    }


def test_a_page_ready_after_its_fallback_shows_the_page(tmp_path: Path) -> None:
    page = templates.render("slides", "Deck", _DECK, 1)
    # The page's script starts only after the fallback timer, as after a slow library.
    at = page.rindex("<script>")
    code = page[at + len("<script>") : page.rindex("</script>")]
    result = run_page(
        tmp_path,
        page[:at] + "</body></html>",
        _STATE
        + f"""
        await wait(60);
        const late = state();
        window.eval({json.dumps(code)});
        await wait(80);
        return {{ late, ready: state() }};
        """,
        marked=True,
        mermaid={"width": 341},
        extra={"fastTimers": True},
    )

    assert result == {
        "late": {"classes": ["nest-fallback"], "source": "block", "ring": "none"},
        "ready": {"classes": ["nest-ready", "nest-started"], "source": "none", "ring": "none"},
    }


def test_a_markdown_pages_raw_html_is_cleaned_and_its_diagrams_drawn(tmp_path: Path) -> None:
    content = f"# Notes\n\n{_HOSTILE}\n\n```mermaid\nflowchart LR\n  A --> B\n```\n"
    result = run_page(
        tmp_path,
        templates.render("markdown", "T", content, 1),
        _CHECK
        + _DIAGRAMS
        + """
        await wait(80);
        return { ...report(document.getElementById("nest-doc")), boxes: boxes() };
        """,
        marked=True,
        mermaid={"width": 341},
    )

    _cleaned(result)
    assert result["tags"] == sorted({*_EXPECTED_TAGS, "h1", "pre"})
    assert result["boxes"] == ["-8 -8 300 100"]


def test_a_markdown_page_loaded_hidden_draws_its_diagrams_once_shown(tmp_path: Path) -> None:
    content = "# A\n\n```mermaid\nflowchart LR\n  A --> B\n```\n"
    result = run_page(
        tmp_path,
        templates.render("markdown", "T", content, 1),
        _DIAGRAMS
        + """
        await wait(60);
        const before = [window.mermaid.calls.length, document.documentElement.className];
        window.__width = 341;
        await wait(80);
        window.dispatchEvent(new window.Event("resize"));
        await wait(40);
        return [before, window.mermaid.calls.length, boxes()];
        """,
        marked=True,
        mermaid={"width": 0},
    )

    # Rendered (ready) at once; the diagram waits for the frame, then is drawn once.
    assert result == [[0, "nest-started nest-ready"], 1, ["-8 -8 300 100"]]


# The design kind presented to decide from: layouts, tabs, the overlay, fitted frames.

_MOCKUPS = json.dumps(
    {
        "intro": "Three **ideas**",
        "screens": [
            {
                "label": "A",
                "title": "Calm",
                "description": "Quiet list",
                "device": "phone",
                "html": "<p>a</p>",
            },
            {
                "label": "B",
                "title": "Dense",
                "device": "desktop",
                "url": "nest.app",
                "html": "<p>b</p>",
            },
            {"label": "C", "title": "Icon", "device": "square", "html": "<p>c</p>"},
        ],
    }
)
_DESIGN_STATE = """
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const viewer = document.getElementById("nest-viewer");
const stages = [...document.querySelectorAll(".mockups .stage")];
const viewing = () => viewer.hidden ? null : [viewer.querySelector(".viewer-badge").textContent,
  viewer.querySelector(".viewer-title").textContent, viewer.querySelector(".viewer-count").textContent];
const key = (name, target = document) => target.dispatchEvent(
  new window.KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true }));
const selectedTab = () => [...document.querySelectorAll('[role="tab"]')]
  .map((tab) => tab.getAttribute("aria-selected")).indexOf("true");
const shown = () => [...document.querySelectorAll(".mockup")].map((m) => m.classList.contains("is-selected"));
"""  # noqa: E501 (embedded JavaScript)


def test_the_intro_and_descriptions_are_rendered_and_screens_mounted(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("design", "D", _MOCKUPS, 1),
        """
        return {
          intro: document.querySelector(".intro-body").innerHTML,
          descriptions: [...document.querySelectorAll(".mockup-desc")].map((d) => d.innerHTML),
          screens: [...document.querySelectorAll(".mockups [data-screen]")].map((host) =>
            host.shadowRoot.querySelector(".nest-body").innerHTML),
          classes: document.documentElement.className,
        };
        """,
        marked=True,
    )

    assert result == {
        "intro": '<div class="prose"><p>Three **ideas**</p></div>',
        "descriptions": ['<div class="prose"><p>Quiet list</p></div>'],
        "screens": ["<p>a</p>", "<p>b</p>", "<p>c</p>"],
        "classes": "nest-started nest-ready",
    }


def test_each_screen_is_fitted_to_its_column(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("design", "D", _MOCKUPS, 1),
        """
        const phone = () => {
          const device = document.querySelector(".device-phone");
          return [device.style.transform, device.parentNode.style.width, device.parentNode.style.height];
        };
        const stack = phone();
        document.querySelector('[data-layout="grid"]:not(body)').click();
        const grid = phone();
        document.querySelector('[data-layout="canvas"]:not(body)').click();
        const canvas = phone();
        return { stack, grid, canvas };
        """,  # noqa: E501 (embedded JavaScript)
        # Every box is 500 wide here; jsdom's window is 768 high.
        mermaid={"width": 500},
    )

    # A stack keeps a screen within the window's height (768 - 120 = 648 of 872).
    scale = 648 / 872
    assert result == {
        "stack": [f"scale({scale})", f"{418 * scale}px", "648px"],
        # A grid card only fits the width, never above the screen's own size.
        "grid": ["scale(1)", "418px", "872px"],
        # The canvas shows every screen at its own size; zoom does the rest.
        "canvas": ["", "418px", "872px"],
    }


def test_the_layout_can_be_switched(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("design", "D", _MOCKUPS, 1),
        """
        const state = () => [document.body.getAttribute("data-layout"),
          [...document.querySelectorAll(".segment")].map((b) => b.getAttribute("aria-pressed")).join(),
          document.getElementById("nest-world").style.transform];
        const seen = [state()];
        for (const name of ["grid", "canvas", "stack"]) {
          document.querySelector(`.segment[data-layout="${name}"]`).click();
          seen.push(state());
        }
        return seen;
        """,  # noqa: E501 (embedded JavaScript)
    )

    assert result == [
        ["stack", "true,false,false,false", ""],
        ["grid", "false,true,false,false", ""],
        ["canvas", "false,false,false,true", "translate(24px, 24px) scale(1)"],
        ["stack", "true,false,false,false", ""],
    ]


def test_tabs_show_one_mockup_and_move_with_keys(tmp_path: Path) -> None:
    content = json.dumps({**json.loads(_MOCKUPS), "layout": "tabs"})
    result = run_page(
        tmp_path,
        templates.render("design", "D", content, 1),
        _DESIGN_STATE
        + """
        const tabs = [...document.querySelectorAll('[role="tab"]')];
        const seen = [[selectedTab(), shown()]];
        key("ArrowRight", tabs[0]); seen.push([selectedTab(), document.activeElement === tabs[1]]);
        key("End", tabs[1]); seen.push(selectedTab());
        key("ArrowRight", tabs[2]); seen.push(selectedTab());
        key("ArrowLeft", tabs[0]); seen.push(selectedTab());
        key("Home", tabs[2]); seen.push(selectedTab());
        key("x", tabs[0]); seen.push(selectedTab());
        tabs[1].click(); seen.push([selectedTab(), shown(), tabs.map((t) => t.tabIndex)]);
        document.querySelector('.segment[data-layout="stack"]').click();
        seen.push(shown());
        return seen;
        """,
    )

    assert result == [
        [0, [True, False, False]],
        [1, True],
        2,
        # Arrows wrap around.
        0,
        2,
        0,
        0,
        [1, [False, True, False], [-1, 0, -1]],
        # Back in a stack, every mockup shows.
        [False, False, False],
    ]


def test_a_screen_opens_fitted_large_and_the_overlay_steps_and_closes(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        templates.render("design", "D", _MOCKUPS, 1),
        _DESIGN_STATE
        + """
        const seen = [viewing()];
        stages[1].click();
        const opened = [viewing(), document.body.classList.contains("is-viewing"),
          document.activeElement === viewer.querySelector(".viewer-close"),
          viewer.querySelector(".viewer-stage [data-screen]").shadowRoot.querySelector(".nest-body").innerHTML,
          viewer.querySelector(".viewer-stage .device").className];
        key("ArrowRight"); seen.push(viewing());
        key("ArrowRight"); seen.push(viewing());
        key("ArrowLeft"); seen.push(viewing());
        viewer.querySelector('[data-step="1"]').click(); seen.push(viewing());
        viewer.querySelector('.viewer-stage .device').click(); seen.push(viewing());
        key("Escape");
        const closed = [viewing(), document.body.classList.contains("is-viewing"),
          document.activeElement === stages[1], viewer.querySelector(".viewer-stage").children.length];
        key("Enter", stages[0]); seen.push(viewing());
        viewer.click(); seen.push(viewing());
        key(" ", stages[2]); viewer.querySelector(".viewer-close").click(); seen.push(viewing());
        stages[0].click(); viewer.querySelector(".viewer-stage").click(); seen.push(viewing());
        key("Escape"); key("ArrowRight");
        // In the canvas a click pans, never opens.
        document.querySelector('.segment[data-layout="canvas"]').click();
        stages[0].click(); key("Enter", stages[0]); seen.push(viewing());
        return { seen, opened, closed };
        """,  # noqa: E501 (embedded JavaScript)
    )

    assert result == {
        "seen": [
            None,
            ["C", "Icon", "3 of 3"],
            ["A", "Calm", "1 of 3"],
            ["C", "Icon", "3 of 3"],
            ["A", "Calm", "1 of 3"],
            # A click on the screen itself keeps it open.
            ["A", "Calm", "1 of 3"],
            ["A", "Calm", "1 of 3"],
            None,
            None,
            None,
            None,
        ],
        "opened": [
            ["B", "Dense", "2 of 3"],
            True,
            True,
            "<p>b</p>",
            "device device-desktop frame-browser",
        ],
        "closed": [None, False, True, 0],
    }
