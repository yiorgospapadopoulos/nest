"""The document a client shows in its sandbox for an artifact version (B82). An HTML artifact
is shown as saved. A Markdown one becomes a Nest-styled page: the source, escaped, in a
`<pre>` that stays readable when the libraries cannot load, then rendered with pinned
marked (GFM), Mermaid and highlight.js from hosts the clients' page policy allows.
"""

import json
from html import escape

from nestd.artifacts.models import ArtifactKind

LIBRARIES = (
    "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js",
    "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js",
)

# Light and dark values of Nest's design tokens (design/tokens.toml; a test keeps them equal).
PALETTE: dict[str, tuple[str, str]] = {
    "bg": ("#eeeeec", "#0c0c0d"),
    "text": ("#1a1b20", "#f2f3f7"),
    "text-2": ("rgba(26,27,32,0.68)", "rgba(242,243,247,0.7)"),
    "text-3": ("rgba(26,27,32,0.64)", "rgba(242,243,247,0.56)"),
    "line": ("rgba(0,0,0,0.08)", "rgba(255,255,255,0.09)"),
    "line-strong": ("rgba(0,0,0,0.16)", "rgba(255,255,255,0.18)"),
    "fill": ("rgba(0,0,0,0.045)", "rgba(255,255,255,0.065)"),
    "fill-strong": ("rgba(0,0,0,0.085)", "rgba(255,255,255,0.12)"),
    "link": ("#0a6fd6", "#4ea7ff"),
    "hl-keyword": ("#4b59d6", "#7f8cff"),
    "hl-string": ("#14723a", "#6be3a0"),
    "hl-number": ("#8f5100", "#ffc466"),
    "hl-title": ("#0a6fd6", "#4ea7ff"),
    "hl-type": ("#bd2c27", "#ff8f88"),
    "hl-meta": ("#6b5d4f", "#c9bba9"),
}

FONTS = {
    "system": '-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display",'
    ' "Helvetica Neue", Helvetica, Arial, sans-serif',
    "mono": 'ui-monospace, "SF Mono", SFMono-Regular, Menlo, Monaco, Consolas, monospace',
}


def _diagram(theme: int) -> dict[str, str | bool]:
    """Mermaid's base theme in Nest's colors (light, then dark): solid hex, since Mermaid
    derives shades from them; pie slices in the accent colors.
    """

    def pick(light: str, dark: str) -> str:
        return dark if theme else light

    page, text = pick("#eeeeec", "#0c0c0d"), pick("#1a1b20", "#f2f3f7")
    box, edge = pick("#f8f8f6", "#171717"), pick("#7f7f7f", "#8c8c8c")
    slices = (
        pick("#a5573a", "#e39a78"),
        pick("#2c6a9a", "#79b4e3"),
        pick("#55702f", "#a5c26f"),
        pick("#a34a62", "#e293a9"),
        pick("#1f7a78", "#5cc4bf"),
        pick("#2b2b2e", "#e6e6e9"),
    )
    return {
        "darkMode": bool(theme),
        "fontFamily": FONTS["system"],
        "background": page,
        "primaryColor": box,
        "secondaryColor": box,
        "tertiaryColor": box,
        "primaryTextColor": text,
        "textColor": text,
        "primaryBorderColor": edge,
        "lineColor": edge,
        "pieTitleTextColor": text,
        "pieLegendTextColor": text,
        "pieSectionTextColor": pick("#ffffff", "#141416"),
        "pieStrokeColor": page,
        "pieOuterStrokeColor": page,
        **{f"pie{index}": color for index, color in enumerate(slices, start=1)},
    }


# Light and dark Mermaid variables (a test keeps them equal to design/tokens.toml).
MERMAID = (_diagram(0), _diagram(1))


def _variables(theme: int) -> str:
    return "\n".join(f"    --nest-{name}: {values[theme]};" for name, values in PALETTE.items())


_STYLE = f"""
  :root {{
    color-scheme: light dark;
{_variables(0)}
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
{_variables(1)}
    }}
  }}
  * {{ box-sizing: border-box; }}
  html {{ -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }}
  body {{
    margin: 0;
    background: var(--nest-bg);
    color: var(--nest-text);
    font: 15px/1.6 {FONTS["system"]};
    overflow-wrap: anywhere;
  }}
  #nest-md,
  #nest-doc {{ max-width: 760px; margin: 0 auto; padding: 20px 16px 32px; }}
  #nest-md {{
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font: 13px/1.55 {FONTS["mono"]};
    background: none;
  }}
  #nest-doc > :first-child {{ margin-top: 0; }}
  #nest-doc > :last-child {{ margin-bottom: 0; }}
  h1, h2, h3, h4, h5, h6 {{ line-height: 1.3; margin: 1.4em 0 0.5em; font-weight: 650; }}
  h1 {{ font-size: 1.6em; }}
  h2 {{ font-size: 1.3em; }}
  h3 {{ font-size: 1.12em; }}
  h4, h5, h6 {{ font-size: 1em; }}
  p, ul, ol, table, pre, blockquote {{ margin: 0 0 0.9em; }}
  ul, ol {{ padding-left: 1.4em; }}
  li + li {{ margin-top: 0.2em; }}
  a {{ color: var(--nest-link); }}
  strong {{ font-weight: 650; }}
  hr {{ border: 0; border-top: 1px solid var(--nest-line-strong); margin: 1.4em 0; }}
  blockquote {{
    margin-left: 0;
    padding-left: 12px;
    border-left: 3px solid var(--nest-line-strong);
    color: var(--nest-text-2);
  }}
  code, pre {{ font-family: {FONTS["mono"]}; font-size: 13px; }}
  :not(pre) > code {{ padding: 1px 5px; border-radius: 5px; background: var(--nest-fill); }}
  pre {{
    padding: 10px 12px;
    border-radius: 8px;
    background: var(--nest-fill);
    overflow-x: auto;
    white-space: pre;
    overflow-wrap: normal;
    line-height: 1.5;
  }}
  pre.mermaid {{ padding: 0; background: none; text-align: center; white-space: pre-wrap; }}
  table {{
    display: block;
    max-width: 100%;
    overflow-x: auto;
    border-collapse: collapse;
    overflow-wrap: normal;
  }}
  th, td {{
    padding: 6px 10px;
    border: 1px solid var(--nest-line-strong);
    text-align: left;
    vertical-align: top;
  }}
  th {{ background: var(--nest-fill-strong); font-weight: 650; }}
  img,
  svg {{ max-width: 100%; }}
  img {{ height: auto; }}
  .hljs-keyword, .hljs-selector-tag, .hljs-name {{ color: var(--nest-hl-keyword); }}
  .hljs-string, .hljs-regexp, .hljs-symbol, .hljs-addition {{ color: var(--nest-hl-string); }}
  .hljs-number, .hljs-literal {{ color: var(--nest-hl-number); }}
  .hljs-title, .hljs-section, .hljs-attr, .hljs-attribute {{ color: var(--nest-hl-title); }}
  .hljs-built_in, .hljs-type, .hljs-deletion {{ color: var(--nest-hl-type); }}
  .hljs-meta, .hljs-variable, .hljs-template-variable {{ color: var(--nest-hl-meta); }}
  .hljs-comment, .hljs-quote {{ color: var(--nest-text-3); font-style: italic; }}
"""

# marked 12 passes the code and info string; later versions pass one token, read too.
_RENDER = """
(function () {
  var source = document.getElementById("nest-md");
  if (!window.marked) return;
  var diagram = DIAGRAMS[window.matchMedia("(prefers-color-scheme: dark)").matches ? 1 : 0];
  function escape(text) {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  var renderer = new marked.Renderer();
  renderer.code = function (code, info) {
    if (typeof code === "object") {
      info = code.lang;
      code = code.text;
    }
    var lang = (info || "").trim().split(/\\s+/)[0].toLowerCase();
    if (lang === "mermaid" && window.mermaid) {
      return '<pre class="mermaid">' + escape(code) + "</pre>";
    }
    if (window.hljs && lang && hljs.getLanguage(lang)) {
      var html = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
      return '<pre><code class="hljs">' + html + "</code></pre>";
    }
    return "<pre><code>" + escape(code) + "</code></pre>";
  };
  var doc = document.createElement("article");
  doc.id = "nest-doc";
  doc.innerHTML = marked.parse(source.textContent, { gfm: true, renderer: renderer });
  source.replaceWith(doc);
  if (window.mermaid) {
    mermaid.initialize({
      startOnLoad: false,
      theme: "base",
      themeVariables: diagram,
      securityLevel: "strict",
    });
    mermaid.run({ nodes: doc.querySelectorAll("pre.mermaid") }).catch(function () {});
  }
})();
"""

_HEAD = (
    '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<meta name="color-scheme" content="light dark">\n<title>'
)
_BODY = f"</title>\n<style>{_STYLE}</style>\n</head>\n<body>\n"
# The parser drops one newline right after `<pre>`, so a leading one of the source is kept.
_SOURCE = '<pre id="nest-md">\n'
_SCRIPTS = "".join(f'<script src="{url}"></script>\n' for url in LIBRARIES)
_TAIL = (
    f"</pre>\n{_SCRIPTS}<script>var DIAGRAMS = {json.dumps(list(MERMAID))};{_RENDER}</script>\n"
    "</body>\n</html>\n"
)


def artifact_page(kind: ArtifactKind, title: str, content: str) -> str:
    if kind == "html":
        return content
    # Escaping &, < and > keeps the source text: nothing in it can close the <pre> or open a tag.
    return _HEAD + escape(title) + _BODY + _SOURCE + escape(content, quote=False) + _TAIL
