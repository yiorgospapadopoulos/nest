"""The shim every artifact page gets (B88): `window.nest`, link clicks and `window.open`
through the bridge, put in before any page script; saveDocument and the iPhone's print event
(stage 2).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from nestd.artifacts.bridge import (
    METHODS,
    SHIM,
    SHIM_TAG,
    USER_ACTIONS,
    init_tag,
    json_script,
    with_shim,
)


def test_the_shim_defines_a_frozen_nest_with_version_one_and_open_link() -> None:
    assert f"<script>{SHIM}</script>" == SHIM_TAG
    assert "</script" not in SHIM.lower()
    assert SHIM.lstrip().startswith("(function () {")
    assert SHIM.rstrip().endswith("})();")
    assert "var api = { version: 1, openLink: openLink, storage: storage, files: fileApi };" in SHIM
    assert "api.saveFile = saveFile;" in SHIM
    assert 'var methods = ["saveDocument"];' in SHIM
    assert 'Object.defineProperty(window, "nest", { value: Object.freeze(api)' in SHIM
    assert 'call("openLink", { url: url })' in SHIM


def test_the_shim_speaks_the_bridge_protocol() -> None:
    assert "{ nest: 1, id: id, method: method, params: params }" in SHIM
    # The Mac's reply handler first, else the parent frame (the iPhone).
    assert "window.webkit.messageHandlers.nest" in SHIM
    assert 'window.parent.postMessage(request, "*")' in SHIM
    # Replies only from the parent, matched by id; calls give up after 120 s.
    assert "event.source !== window.parent" in SHIM
    assert "reply.nest !== 1" in SHIM
    assert "120000" in SHIM
    assert '"unavailable"' in SHIM
    assert "error.code = code" in SHIM


def test_the_shim_routes_links_and_window_open() -> None:
    assert 'document.addEventListener("click", onClick, true)' in SHIM
    assert 'closest("a[href]")' in SHIM
    assert "event.preventDefault()" in SHIM
    # In-page anchors scroll inside the page, never by navigating: an iPhone srcdoc frame
    # resolves "#x" against the app's own URL, so the raw attribute decides.
    assert 'if (raw.charAt(0) === "#") return jump(raw.slice(1));' in SHIM
    assert "href.slice(0, mark) === here" in SHIM
    assert SHIM.index("event.preventDefault()") < SHIM.index("return jump(")
    assert "decodeURIComponent(fragment)" in SHIM
    assert "document.getElementById(name) || document.getElementsByName(name)[0]" in SHIM
    assert "target.scrollIntoView()" in SHIM
    assert 'name.toLowerCase() === "top"' in SHIM
    assert "window.scrollTo(0, 0)" in SHIM
    assert "location.hash" not in SHIM
    assert "history" not in SHIM
    assert "window.open = function (url)" in SHIM
    assert "return null;" in SHIM


@pytest.mark.parametrize(
    "doctype",
    [
        "<!doctype html>",
        "<!DOCTYPE html>",
        '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01//EN">',
        "\ufeff<!doctype html>",
        "\n  \t<!doctype html>",
        "<!-- made by an agent -->\n<!doctype html>",
        "\ufeff <!-- a --><!--b-->\n<!doctype html>",
    ],
)
def test_the_shim_goes_right_after_a_leading_doctype(doctype: str) -> None:
    rest = "\n<html><head><script>start()</script></head></html>"

    assert with_shim(doctype + rest) == doctype + SHIM_TAG + rest


@pytest.mark.parametrize(
    ("document", "prefix"),
    [
        ("<html><script>start()</script></html>", ""),
        ("<script>start()</script>", ""),
        ("", ""),
        # A BOM stays first.
        ("\ufeff<html></html>", "\ufeff"),
        # A doctype that does not lead is not the document's doctype.
        ("<p>x</p><!doctype html>", ""),
        # An unclosed comment hides the doctype.
        ("<!-- open <!doctype html>", ""),
    ],
)
def test_without_a_leading_doctype_the_shim_goes_first(document: str, prefix: str) -> None:
    assert with_shim(document) == prefix + SHIM_TAG + document.removeprefix(prefix)


def test_the_other_methods_are_plain_calls_on_the_frozen_nest() -> None:
    assert METHODS == ("saveDocument",)
    assert "api[name] = function (params) {" in SHIM
    assert "return call(name, params === undefined ? {} : params);" in SHIM
    assert SHIM.index("methods.forEach(") < SHIM.index("Object.freeze(api)")


def test_saving_needs_a_trusted_user_action_in_the_last_five_seconds() -> None:
    assert USER_ACTIONS == {"saveDocument": "Saving needs a click on Save"}
    assert 'var userActions = {"saveDocument": "Saving needs a click on Save"};' in SHIM
    # A guard against accidental saves: Date.now is kept before any page script runs.
    assert SHIM.index("var now = Date.now;") < SHIM.index("function call(")
    assert "event.isTrusted === true" in SHIM
    assert 'window.addEventListener("click", trust, true);' in SHIM
    assert 'window.addEventListener("keydown", trust, true);' in SHIM
    assert "now() - trusted <= 5000" in SHIM


def test_the_print_event_comes_only_from_the_parent_and_uses_the_real_print() -> None:
    # Kept before any page script runs, so a page that replaces print cannot stop it.
    assert SHIM.index("var realPrint = window.print;") < SHIM.index("function call(")
    assert 'data.nest === 1 && data.event === "print"' in SHIM
    assert "realPrint.call(window)" in SHIM
    listener = SHIM.split('window.addEventListener("message"', 1)[1]
    assert listener.index("event.source !== window.parent") < listener.index("printPage()")


# The shim run in node against fake window and document objects: both transports, links,
# anchors, window.open, timeouts, saveDocument and the print event.
_CHECK = r"""
import vm from "node:vm";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const plain = readFileSync(process.argv[2], "utf8");

function makeEnv({ mac, source = plain, print, clock } = {}) {
  const listeners = { message: [], click: [] };
  const own = { click: [], keydown: [], message: listeners.message };
  const posted = [];
  const parent = { postMessage: (msg, origin) => posted.push({ msg, origin }) };
  const window = {
    addEventListener: (type, fn, capture) => {
      if (type !== "message") assert.equal(capture, true);
      own[type].push(fn);
    },
    parent,
    open: () => "real",
    scrolls: [],
    scrollTo: (x, y) => window.scrolls.push(["top", x, y]),
  };
  if (print) window.print = print;
  const element = (label) => ({
    scrollIntoView: (...args) => window.scrolls.push([label, args.length]),
  });
  const ids = { section: element("id:section"), "café": element("id:café") };
  const names = { old: [element("name:old")] };
  if (mac) window.webkit = { messageHandlers: { nest: mac } };
  const document = {
    baseURI: "about:srcdoc",
    getElementById: (id) => ids[id] || null,
    getElementsByName: (name) => names[name] || [],
    addEventListener: (type, fn, capture) => {
      assert.equal(capture, true);
      listeners[type].push(fn);
    },
  };
  const context = {
    window, document, location: { href: "about:srcdoc" },
    setTimeout, clearTimeout, Promise, Math, Error, Object, URL, String,
  };
  if (clock) context.Date = { now: () => clock.now };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { window, document, listeners, own, posted, parent };
}

function link(href) {
  const a = {
    href: new URL(href, "http://127.0.0.1:8812/chat/abc").href,
    getAttribute: () => href,
  };
  return { closest: () => a };
}

function click(env, target) {
  let prevented = false;
  env.listeners.click[0]({
    target, defaultPrevented: false, preventDefault: () => { prevented = true; },
  });
  return prevented;
}

const results = [];

// iPhone transport.
{
  const env = makeEnv();
  const nest = env.window.nest;
  assert.equal(nest.version, 1);
  assert.ok(Object.isFrozen(nest));
  assert.deepEqual(Object.keys(nest).sort(), ["ask", "files", "onUsage", "openLink",
    "saveDocument", "saveFile", "storage", "usage", "version"]);
  assert.equal(env.window.__nestHost, undefined, "host events come from the parent here");
  assert.throws(() => { env.window.nest = "x"; }, TypeError);
  assert.equal(env.window.nest, nest, "nest is not replaceable");

  const p = nest.openLink("https://example.com/");
  assert.equal(env.posted.length, 1);
  const { msg, origin } = env.posted[0];
  assert.equal(origin, "*");
  assert.deepEqual({ ...msg, params: { ...msg.params } }, {
    nest: 1, id: msg.id, method: "openLink", params: { url: "https://example.com/" },
  });
  assert.match(msg.id, /^1-[a-z0-9]+$/);
  const message = env.listeners.message[0];
  // A fake reply from the page itself is ignored, and so is junk from the parent.
  message({ source: env.window,
    data: { nest: 1, id: msg.id, ok: true, result: { opened: false } } });
  for (const data of [null, "x", 1, { nest: 2, id: msg.id },
    { nest: 1, id: "constructor", ok: true }, { nest: 1, id: "nope", ok: true }]) {
    message({ source: env.parent, data });
  }
  message({ source: env.parent,
    data: { nest: 1, id: msg.id, ok: true, result: { opened: true } } });
  assert.deepEqual({ ...(await p) }, { opened: true });

  const q = nest.openLink("javascript:alert(1)");
  const id2 = env.posted[1].msg.id;
  assert.notEqual(id2, msg.id);
  message({ source: env.parent, data: { nest: 1, id: id2, ok: false,
    error: { code: "bad_request", message: "Not a web link" } } });
  await assert.rejects(q, (e) => e.code === "bad_request" && e.message === "Not a web link");
  const r = nest.openLink("https://a.example/");
  message({ source: env.parent, data: { nest: 1, id: env.posted[2].msg.id, ok: false } });
  await assert.rejects(r, (e) => e.code === "unavailable");

  // In-page anchors are prevented (the srcdoc frame would load the app) and scrolled.
  const scrolled = () => env.window.scrolls.splice(0);
  assert.equal(click(env, link("#section")), true);
  assert.deepEqual(scrolled(), [["id:section", 0]]);
  assert.equal(click(env, link("#caf%C3%A9")), true);
  assert.deepEqual(scrolled(), [["id:café", 0]]);
  assert.equal(click(env, link("#old")), true);
  assert.deepEqual(scrolled(), [["name:old", 0]]);
  for (const top of ["#top", "#TOP", "#"]) {
    assert.equal(click(env, link(top)), true);
    assert.deepEqual(scrolled(), [["top", 0, 0]]);
  }
  assert.equal(click(env, link("#missing")), true);
  assert.deepEqual(scrolled(), []);
  assert.equal(click(env, link("#%E0%A4%A")), true);
  assert.deepEqual(scrolled(), []);
  assert.equal(env.posted.length, 3, "anchors never reach Nest");
  // Other pages, even with a fragment, go to openLink.
  assert.equal(click(env, link("https://other.example/page#part")), true);
  assert.equal(env.posted.at(-1).msg.params.url, "https://other.example/page#part");
  assert.equal(click(env, link("mailto:a@b.c")), true);
  assert.equal(env.posted.at(-1).msg.params.url, "mailto:a@b.c");
  assert.equal(click(env, { closest: () => null }), false);
  assert.equal(click(env, {}), false);
  assert.equal(click(env, null), false);
  assert.equal(click(env, { closest: () => { throw new Error("boom"); } }), true);
  let again = false;
  env.listeners.click[0]({ target: link("https://x.example/"), defaultPrevented: true,
    preventDefault: () => { again = true; } });
  assert.equal(again, false);

  // window.open goes through the bridge and returns null.
  assert.equal(env.window.open("https://open.example/"), null);
  assert.equal(env.posted.at(-1).msg.params.url, "https://open.example/");
  const before = env.posted.length;
  assert.equal(env.window.open(), null);
  assert.equal(env.window.open(""), null);
  assert.equal(env.posted.length, before);
  results.push("iphone");
}

// Storage events from the app come from the parent only, and reach the cache.
{
  const env = makeEnv();
  const message = env.listeners.message[0];
  const seen = [];
  env.window.nest.storage.onChange((change) => seen.push([change.key, change.value]));
  message({ source: env.window, data: { nest: 1, event: "storage", key: "a", value: "fake" } });
  assert.equal(env.window.nest.storage.get("a"), null);
  message({ source: env.parent, data: { nest: 1, event: "storage", key: "a", value: "1" } });
  assert.equal(env.window.nest.storage.get("a"), "1");
  assert.equal(env.window.localStorage.getItem("a"), "1");
  message({ source: env.parent, data: { nest: 1, event: "storage", clear: true } });
  assert.deepEqual(env.window.nest.storage.keys(), []);
  assert.deepEqual(seen, [["a", "1"], [null, null]]);
  results.push("storage events");
}

// Usage events from the app come from the parent only.
{
  const env = makeEnv();
  const message = env.listeners.message[0];
  const seen = [];
  env.window.nest.onUsage((usage) => seen.push(usage.today.tokens));
  assert.equal(env.posted[0].msg.method, "usage");
  const usageEvent = (tokens) => ({ nest: 1, event: "usage", usage: { today: { tokens } } });
  message({ source: env.window, data: usageEvent(1) });
  message({ source: env.parent, data: usageEvent(2) });
  assert.deepEqual(seen, [2]);
  results.push("usage events");
}

// saveDocument is refused without a trusted click or key press in the last 5 seconds.
{
  const clock = { now: 1000 };
  const env = makeEnv({ clock });
  const refused = (promise) => assert.rejects(promise,
    (e) => e.code === "bad_request" && e.message === "Saving needs a click on Save");
  await refused(env.window.nest.saveDocument({ content: "x", base_version: 1 }));
  // A page's own events are not trusted.
  for (const listen of [...env.own.click, ...env.own.keydown]) listen({ isTrusted: false });
  env.own.click[0](null);
  await refused(env.window.nest.saveDocument({ content: "x", base_version: 1 }));
  assert.equal(env.posted.length, 0);
  env.own.keydown[0]({ isTrusted: true });
  clock.now += 5000;
  env.window.nest.saveDocument({ content: "y", base_version: 1 });
  assert.equal(env.posted.length, 1);
  clock.now += 1;
  await refused(env.window.nest.saveDocument({ content: "z", base_version: 1 }));
  assert.equal(env.posted.length, 1);
  results.push("user action");
}

// saveDocument is a plain call with its params, or an empty object.
{
  const env = makeEnv();
  env.own.click[0]({ isTrusted: true });
  const saved = env.window.nest.saveDocument({ content: "# A", base_version: 3 });
  const request = env.posted[0].msg;
  assert.equal(request.method, "saveDocument");
  assert.deepEqual({ ...request.params }, { content: "# A", base_version: 3 });
  env.listeners.message[0]({ source: env.parent,
    data: { nest: 1, id: request.id, ok: false,
      error: { code: "conflict", message: "Changed" } } });
  await assert.rejects(saved, (e) => e.code === "conflict" && e.message === "Changed");
  env.own.click[0]({ isTrusted: true });
  env.window.nest.saveDocument();
  assert.deepEqual({ ...env.posted[1].msg.params }, {});
  results.push("methods");
}

// The print event: only from the parent, with the print the page had first.
{
  let printed = 0;
  const env = makeEnv({ print() { printed += 1; assert.equal(this, env.window); } });
  env.window.print = () => { throw new Error("replaced by the page"); };
  const message = env.listeners.message[0];
  message({ source: env.window, data: { nest: 1, event: "print" } });
  message({ source: env.parent, data: { nest: 2, event: "print" } });
  message({ source: env.parent, data: { nest: 1, event: "other" } });
  assert.equal(printed, 0);
  message({ source: env.parent, data: { nest: 1, event: "print" } });
  assert.equal(printed, 1);
  // A print that throws, or a page without print, never throws into the page.
  const failing = makeEnv({ print() { throw new Error("no printer"); } });
  failing.listeners.message[0]({ source: failing.parent, data: { nest: 1, event: "print" } });
  const none = makeEnv();
  none.listeners.message[0]({ source: none.parent, data: { nest: 1, event: "print" } });
  results.push("print");
}

// Same-document link with a fragment (resolved href equals location plus #).
{
  const env = makeEnv();
  const a = { href: "about:srcdoc#section", getAttribute: () => "about:srcdoc#section" };
  assert.equal(click(env, { closest: () => a }), true);
  assert.deepEqual(env.window.scrolls, [["id:section", 0]]);
  assert.equal(env.posted.length, 0);
  results.push("same document");
}

// Mac transport: no message listener, so no print event either.
{
  const mac = {
    postMessage: (msg) => {
      if (msg.params.url === "https://fail.example/") return Promise.reject(new Error("x"));
      return Promise.resolve({ nest: 1, id: msg.id, ok: true, result: { opened: true } });
    },
  };
  const env = makeEnv({ mac });
  assert.equal(env.listeners.message.length, 0, "no message listener on the Mac");
  // The app calls this with host events instead: hidden, fixed and frozen.
  const host = Object.getOwnPropertyDescriptor(env.window, "__nestHost");
  assert.deepEqual([host.enumerable, host.writable, host.configurable], [false, false, false]);
  assert.ok(Object.isFrozen(host.value));
  host.value({ nest: 1, event: "storage", key: "k", value: "v" });
  assert.equal(env.window.nest.storage.get("k"), "v");
  const usages = [];
  env.window.nest.onUsage((usage) => usages.push(usage.week));
  host.value({ nest: 1, event: "usage", usage: { week: 7 } });
  assert.deepEqual(usages, [7]);
  const opened = await env.window.nest.openLink("https://example.com/");
  assert.deepEqual({ ...opened }, { opened: true });
  assert.equal(env.posted.length, 0);
  await assert.rejects(env.window.nest.openLink("https://fail.example/"),
    (e) => e.code === "unavailable");
  const silent = makeEnv({ mac: { postMessage: () => undefined } });
  await assert.rejects(silent.window.nest.openLink("https://example.com/"),
    (e) => e.code === "unavailable");
  results.push("mac");
}

// A top-level page with no host.
{
  const listeners = { message: [], click: [], keydown: [] };
  const window = { addEventListener: (t, f) => listeners[t].push(f) };
  window.parent = window;
  const context = { window, document: { addEventListener: (t, f) => listeners[t].push(f) },
    location: { href: "x" }, setTimeout, clearTimeout, Promise, Math, Error, Object, URL, String };
  vm.createContext(context);
  vm.runInContext(plain, context);
  await assert.rejects(window.nest.openLink("https://a.example/"), (e) => e.code === "unavailable");
  results.push("top level");
}

// Calls give up after 120 s.
{
  const timers = [];
  const window = { addEventListener: () => {}, parent: { postMessage: () => {} } };
  const context = {
    window, document: { addEventListener: () => {} }, location: { href: "x" },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    clearTimeout: () => {}, Promise, Math, Error, Object, URL, String,
  };
  vm.createContext(context);
  vm.runInContext(plain, context);
  const p = window.nest.openLink("https://a.example/");
  assert.equal(timers[0].ms, 120000);
  timers[0].fn();
  await assert.rejects(p, (e) => e.code === "unavailable" && e.message === "Nest did not answer");
  results.push("timeout");
}

console.log(JSON.stringify(results));
process.exit(0);
"""


def test_the_shim_behaves_under_node(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    check = tmp_path / "check.mjs"
    check.write_text(_CHECK, encoding="utf-8")
    (tmp_path / "shim.js").write_text(SHIM, encoding="utf-8")

    done = subprocess.run(  # noqa: S603
        [node, str(check), str(tmp_path / "shim.js")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [
        "iphone",
        "storage events",
        "usage events",
        "user action",
        "methods",
        "print",
        "same document",
        "mac",
        "top level",
        "timeout",
    ]


# Stage 3: the page's initial data (what it stored, its files) in a JSON element the shim reads
# once. It goes right before the shim: a script cannot see elements parsed after it.


def test_json_for_a_script_element_cannot_end_it() -> None:
    data = {"v": "</script><script>alert(1)</script><!-- & \u2028\u2029 >"}

    tag = json_script("nest-init", data)

    head = '<script type="application/json" id="nest-init">'
    assert tag.startswith(head)
    assert tag.endswith("</script>")
    inner = tag.removeprefix(head).removesuffix("</script>")
    for raw in ("<", ">", "&", "\u2028", "\u2029"):
        assert raw not in inner
    assert json.loads(inner) == data


def test_the_init_data_goes_right_before_the_shim() -> None:
    init: dict[str, object] = {"storage": {"done": "</script><b>"}, "files": []}
    document = "<!doctype html>\n<p>x</p><script>start()</script>"

    shown = with_shim(document, init)

    assert init_tag(init) == json_script("nest-init", init)
    assert (
        shown
        == "<!doctype html>" + init_tag(init) + SHIM_TAG + "\n<p>x</p><script>start()</script>"
    )
    assert "</script><b>" not in shown


def test_without_init_data_only_the_shim_goes_in() -> None:
    assert with_shim("<p>x</p>") == SHIM_TAG + "<p>x</p>"
    assert with_shim("<p>x</p>", None) == SHIM_TAG + "<p>x</p>"
    assert with_shim("\ufeff<p>x</p>", {"storage": {}}) == (
        "\ufeff" + init_tag({"storage": {}}) + SHIM_TAG + "<p>x</p>"
    )


def test_the_shim_offers_usage_and_ask() -> None:
    assert "api.usage = usage;" in SHIM
    assert "api.onUsage = onUsage;" in SHIM
    assert "api.ask = ask;" in SHIM
    assert 'call("usage", {})' in SHIM
    assert 'call("ask", request)' in SHIM


def test_the_shim_reads_its_init_data_once_and_removes_it() -> None:
    assert 'document.getElementById("nest-init")' in SHIM
    assert "node.parentNode.removeChild(node)" in SHIM
    assert SHIM.index("readInit()") < SHIM.index("function call(")
