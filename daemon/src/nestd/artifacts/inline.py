"""A multi-file HTML page made one document (B88 stage 3, D117). The sandbox loads nothing
from Nest, so the page's own files that it names by a relative path are put inline:
`<script src>` gets the file's text, `<link rel="stylesheet" href>` becomes a `<style>`, and
`<img src>` and `url()` in CSS (inlined stylesheets, `<style>` elements and style attributes)
become data: URIs. Absolute and CDN URLs, unknown files and anything inside other scripts,
styles and comments are left as written.
"""

import base64
import posixpath
import re
from collections.abc import Callable
from html import escape, unescape

from nestd.artifacts.files import FileData

_RAW = re.compile(r"<!--.*?-->|<(script|style)\b([^>]*)>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<([A-Za-z][A-Za-z0-9-]*)(\s[^>]*)?>")
_ATTRIBUTE = re.compile(r"""([^\s"'>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?""")
_URL = re.compile(r"""url\(\s*(['"]?)([^'")]*?)\1\s*\)""", re.IGNORECASE)
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")

type _Attributes = list[tuple[str, str | None]]
type _Files = dict[str, FileData]


def inline(page: str, files: list[FileData]) -> str:
    if not files:
        return page
    by_path = {file.path: file for file in files}
    parts: list[str] = []
    at = 0
    for found in _RAW.finditer(page):
        parts.append(_markup(page[at : found.start()], by_path))
        parts.append(_raw(found, by_path))
        at = found.end()
    parts.append(_markup(page[at:], by_path))
    return "".join(parts)


def _raw(found: re.Match[str], files: _Files) -> str:
    element = (found.group(1) or "").lower()
    if element == "style":
        return found.group(0).replace(found.group(3), _css(found.group(3), "", files), 1)
    if element == "script":
        attributes = _attributes(found.group(2))
        source = _resolve(_value(attributes, "src"), "", files)
        if source is not None and not found.group(3).strip():
            kept = [(name, value) for name, value in attributes if name != "src"]
            return f"<script{_rendered(kept)}>{_script_text(source)}</script>"
    return found.group(0)


def _markup(text: str, files: _Files) -> str:
    return _TAG.sub(lambda tag: _tag(tag, files), text)


def _tag(tag: re.Match[str], files: _Files) -> str:
    name = tag.group(1).lower()
    raw = tag.group(2) or ""
    attributes = _attributes(raw)
    if name == "link" and "stylesheet" in (_value(attributes, "rel") or "").lower().split():
        sheet = _resolve(_value(attributes, "href"), "", files)
        if sheet is not None:
            base = posixpath.dirname(sheet.path)
            return f"<style>{_style_text(_css(_text(sheet), base, files))}</style>"
    changed = False
    rewritten: _Attributes = []
    for key, value in attributes:
        new = value
        if value is not None and name == "img" and key == "src":
            image = _resolve(value, "", files)
            new = value if image is None else _data_uri(image)
        elif value is not None and key == "style":
            new = _css(value, "", files)
        changed = changed or new != value
        rewritten.append((key, new))
    if not changed:
        return tag.group(0)
    closing = " /" if raw.rstrip().endswith("/") else ""
    return f"<{name}{_rendered(rewritten)}{closing}>"


def _css(css: str, base: str, files: _Files) -> str:
    def url(found: re.Match[str]) -> str:
        target = _resolve(found.group(2), base, files)
        return found.group(0) if target is None else f'url("{_data_uri(target)}")'

    return _URL.sub(url, css)


def _resolve(reference: str | None, base: str, files: _Files) -> FileData | None:
    """The page's file a relative reference names, if any."""
    if reference is None:
        return None
    ref = reference.strip()
    if not ref or _SCHEME.match(ref) or ref.startswith(("/", "#", "\\")):
        return None
    path = posixpath.normpath(posixpath.join(base, re.split(r"[?#]", ref, maxsplit=1)[0]))
    return files.get(path)


def _attributes(raw: str) -> _Attributes:
    found: _Attributes = []
    for match in _ATTRIBUTE.finditer(raw):
        name, double, single, bare = match.groups()
        value = next((v for v in (double, single, bare) if v is not None), None)
        found.append((name.lower(), None if value is None else unescape(value)))
    return found


def _value(attributes: _Attributes, name: str) -> str | None:
    return next((value for key, value in attributes if key == name), None)


def _rendered(attributes: _Attributes) -> str:
    return "".join(
        f" {name}" if value is None else f' {name}="{escape(value)}"' for name, value in attributes
    )


def _text(file: FileData) -> str:
    return file.data.decode("utf-8", "replace")


def _escaped(pattern: str) -> Callable[[str], str]:
    closing = re.compile(rf"</({pattern})", re.IGNORECASE)
    return lambda text: closing.sub(r"<\\/\1", text)


_close_script = _escaped("script")
_style_text = _escaped("style")


def _script_text(file: FileData) -> str:
    """Nothing in it can end the element or start the parser's escaped mode."""
    return _close_script(_text(file)).replace("<!--", "<\\!--")


def _data_uri(file: FileData) -> str:
    return f"data:{file.mime};base64,{base64.b64encode(file.data).decode()}"
