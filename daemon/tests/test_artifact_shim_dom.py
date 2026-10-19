"""The shim's page API in jsdom (B88 stage 3): `nest.storage` with a synchronous cache from
the init data, coalesced writes, caps and changes from other devices; `localStorage` and
`sessionStorage` stand-ins; `nest.files`; `nest.saveFile`. The app's side is the Mac's reply
handler, faked by the harness with queued replies.
"""

import base64
import json
from pathlib import Path
from typing import Any

from nestd.artifacts.bridge import with_shim
from tests.test_artifact_templates_dom import run_page

_PAGE = "<!doctype html><html><head><title>T</title></head><body><p>page</p></body></html>"
_WAIT = "const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));\n"


def _page(init: dict[str, Any] | None) -> str:
    return with_shim(_PAGE, init)


def test_stored_values_are_there_at_once_through_every_api(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        _page({"storage": {"a": "1", "b": "x", "odd": 5}, "files": []}),
        """
        const local = window.localStorage;
        return {
          get: [window.nest.storage.get("a"), window.nest.storage.get("missing")],
          keys: window.nest.storage.keys(),
          local: [local.getItem("b"), local.getItem("missing"), local.length, local.key(0), local.key(1),
            local.key(2), local.key(-1), local.a, local.missing, "a" in local, "missing" in local,
            Object.keys(local), JSON.stringify(local)],
          init: document.getElementById("nest-init"),
          session: [window.sessionStorage.length, window.sessionStorage.getItem("a")],
        };
        """,  # noqa: E501 (embedded JavaScript)
    )

    assert result == {
        "get": ["1", None],
        # A value that is not a string is left out.
        "keys": ["a", "b"],
        "local": [
            "x",
            None,
            2,
            "a",
            "b",
            None,
            None,
            "1",
            None,
            True,
            False,
            ["a", "b"],
            '{"a":"1","b":"x"}',
        ],
        # Read once and removed, so the page cannot read or change it afterwards.
        "init": None,
        "session": [0, None],
    }


def test_writes_are_coalesced_into_one_call_at_most_every_300_ms(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        _page({"storage": {"c": "old"}}),
        _WAIT
        + """
        const storage = window.nest.storage;
        const done = Promise.all([storage.set("a", "1"), storage.set("b", "2"), storage.remove("c"),
          storage.set("a", "3")]).then(() => "written");
        const first = [requests.length, storage.get("a"), storage.get("c"), storage.keys()];
        await wait(350);
        const settled = await done;
        // localStorage coerces like the real one, and writes through the same way.
        window.localStorage.setItem("n", 5);
        window.localStorage.obj = { x: 1 };
        delete window.localStorage.b;
        window.localStorage.removeItem("missing");
        const local = [window.localStorage.getItem("n"), window.localStorage.obj, window.localStorage.length];
        await wait(350);
        return { first, settled, local, requests: requests.map((r) => [r.method, r.params]) };
        """,  # noqa: E501 (embedded JavaScript)
        replies=[],
    )

    assert result == {
        "first": [0, "3", None, ["a", "b"]],
        "settled": "written",
        "local": ["5", "[object Object]", 3],
        "requests": [
            ["storageWrite", {"set": {"a": "3", "b": "2"}, "remove": ["c"]}],
            [
                "storageWrite",
                {"set": {"n": "5", "obj": "[object Object]"}, "remove": ["b", "missing"]},
            ],
        ],
    }


def test_clear_goes_at_once_after_writes_already_on_their_way(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        _page({"storage": {"a": "1"}}),
        _WAIT
        + """
        const storage = window.nest.storage;
        const before = storage.set("b", "2").then(() => "write settled");
        const cleared = storage.clear().then(() => "cleared");
        const after = [storage.keys(), window.localStorage.length];
        storage.set("c", "3");
        await wait(350);
        window.localStorage.clear();
        await wait(50);
        return { after, settled: await Promise.all([before, cleared]),
          requests: requests.map((r) => [r.method, r.params]) };
        """,
        replies=[],
    )

    assert result == {
        "after": [[], 0],
        "settled": ["write settled", "cleared"],
        # The write cleared before it was sent is not sent.
        "requests": [
            ["storageClear", {}],
            ["storageWrite", {"set": {"c": "3"}, "remove": []}],
            ["storageClear", {}],
        ],
    }


def test_writes_over_a_cap_are_refused_and_change_nothing(tmp_path: Path) -> None:
    big = 255 * 1024
    stored = {f"k{i}": "v" * big for i in range(8)}
    result = run_page(
        tmp_path,
        _page({"storage": stored}),
        _WAIT
        + f"""
        const storage = window.nest.storage;
        const refused = (promise) => promise.then(() => "stored", (e) => e.code + ": " + e.message);
        const tries = [
          await refused(storage.set("one", "x".repeat(256 * 1024 + 1))),
          await refused(storage.set("é", "é".repeat(128 * 1024 + 1))),
          await refused(storage.set("new", "x".repeat(20 * 1024))),
          await refused(storage.set("x".repeat(257), "v")),
          await refused(storage.set("", "v")),
          await refused(storage.set("n", 5)),
          // Replacing a value counts its new size only.
          await refused(storage.set("k0", "w".repeat({big}))),
        ];
        let local;
        try {{ window.localStorage.setItem("new", "x".repeat(20 * 1024)); }}
        catch (error) {{
          local = [error.name, error.message, error instanceof window.DOMException];
        }}
        await wait(350);
        return {{ tries, local, kept: [storage.get("new"), storage.keys().length],
          requests: requests.map((r) => [r.method, Object.keys(r.params.set), r.params.remove]) }};
        """,
        replies=[],
    )

    assert result == {
        "tries": [
            "quota: A value may be at most 256 KiB",
            "quota: A value may be at most 256 KiB",
            "quota: Storage may hold at most 2 MiB",
            "bad_request: A key is 1 to 256 characters",
            "bad_request: A key is 1 to 256 characters",
            "bad_request: A value is a string; store JSON.stringify(value)",
            "stored",
        ],
        "local": ["QuotaExceededError", "Storage may hold at most 2 MiB", True],
        "kept": [None, 8],
        "requests": [["storageWrite", ["k0"], []]],
    }


def test_at_most_1000_keys_are_kept(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        _page({"storage": {f"k{i}": "v" for i in range(1000)}}),
        """
        const storage = window.nest.storage;
        const refused = await storage.set("one more", "v").then(() => "stored", (e) => e.code + ": " + e.message);
        return [refused, await storage.set("k1", "changed").then(() => "stored")];
        """,  # noqa: E501 (embedded JavaScript)
        replies=[],
    )

    assert result == ["quota: Storage may hold at most 1,000 keys", "stored"]


def test_a_cap_the_app_reports_rejects_the_write(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        _page({"storage": {}}),
        _WAIT
        + """
        const write = window.nest.storage.set("a", "1").then(() => "stored", (e) => e.code + ": " + e.message);
        await wait(350);
        return await write;
        """,  # noqa: E501 (embedded JavaScript)
        replies=[
            {"ok": False, "error": {"code": "quota", "message": "Storage may hold at most 2 MiB"}}
        ],
    )

    assert result == "quota: Storage may hold at most 2 MiB"


def test_changes_from_other_devices_reach_the_cache_and_listeners(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        _page({"storage": {"a": "1", "b": "2"}}),
        _WAIT
        + """
        const seen = [];
        const events = [];
        const host = window.__nestHost;
        const off = window.nest.storage.onChange((change) => seen.push([change.key, change.value]));
        window.addEventListener("storage", (event) => events.push([event.key, event.newValue]));
        window.nest.storage.onChange(() => { throw new Error("a listener that fails"); });
        host({ nest: 1, event: "storage", key: "a", value: "changed" });
        host({ nest: 1, event: "storage", key: "b", value: null });
        // The echo of a value the page already has is not a change.
        host({ nest: 1, event: "storage", key: "a", value: "changed" });
        // A key the page is about to write keeps the page's value.
        window.nest.storage.set("mine", "local");
        host({ nest: 1, event: "storage", key: "mine", value: "remote" });
        const during = window.nest.storage.get("mine");
        host({ nest: 2, event: "storage", key: "a", value: "x" });
        host({ nest: 1, event: "other" });
        host(null);
        host({ nest: 1, event: "storage", clear: true });
        const cleared = window.nest.storage.keys();
        off();
        host({ nest: 1, event: "storage", key: "late", value: "1" });
        return {
          seen, events, during, cleared, late: window.localStorage.getItem("late"),
          host: [Object.keys(window).includes("__nestHost"), Object.isFrozen(host),
            Object.getOwnPropertyDescriptor(window, "__nestHost").writable],
        };
        """,
        replies=[],
    )

    assert result == {
        "seen": [["a", "changed"], ["b", None], [None, None]],
        "events": [["a", "changed"], ["b", None], [None, None], ["late", "1"]],
        "during": "local",
        # A clear from elsewhere keeps the write the page has not sent yet.
        "cleared": ["mine"],
        "late": "1",
        "host": [False, True, False],
    }


def test_session_storage_lives_in_the_page_only(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        _page({"storage": {"a": "local"}}),
        _WAIT
        + """
        const session = window.sessionStorage;
        session.setItem("a", 1);
        session.b = true;
        const before = [session.getItem("a"), session.b, session.length, session.key(1)];
        session.removeItem("a");
        const after = [session.length, window.localStorage.getItem("a")];
        session.clear();
        await wait(350);
        return { before, after, cleared: session.length, requests: requests.length };
        """,
        replies=[],
    )

    assert result == {
        "before": ["1", "true", 2, "b"],
        "after": [1, "local"],
        "cleared": 0,
        "requests": 0,
    }


def _file(path: str, data: bytes, mime: str) -> dict[str, Any]:
    return {"path": path, "size": len(data), "mime": mime, "data": base64.b64encode(data).decode()}


def test_the_artifacts_files_are_read_through_nest_files(tmp_path: Path) -> None:
    text = "héllo ✓\n".encode()
    files = [
        _file("data/notes.txt", text, "text/plain"),
        _file("logo.png", b"\x89PNG\r\n", "image/png"),
        {"path": "broken", "size": 1},
    ]
    result = run_page(
        tmp_path,
        _page({"storage": {}, "files": files}),
        """
        const files = window.nest.files;
        let missing;
        try { files.text("nope.txt"); } catch (error) { missing = [error.code, error.message]; }
        return {
          list: files.list(),
          text: files.text("data/notes.txt"),
          data: files.dataUrl("logo.png"),
          blob: [files.blobUrl("logo.png"), files.blobUrl("logo.png"), files.blobUrl("data/notes.txt")],
          missing,
          frozen: Object.isFrozen(files) && Object.isFrozen(window.nest.storage),
        };
        """,  # noqa: E501 (embedded JavaScript)
    )

    assert result == {
        "list": [
            {"path": "data/notes.txt", "size": len(text), "mime": "text/plain"},
            {"path": "logo.png", "size": 6, "mime": "image/png"},
        ],
        "text": "héllo ✓\n",
        "data": "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n").decode(),
        # One blob URL per file, made once.
        "blob": [
            "blob:nest/1/image/png/6",
            "blob:nest/1/image/png/6",
            f"blob:nest/2/text/plain/{len(text)}",
        ],
        "missing": ["bad_request", "This artifact has no file nope.txt"],
        "frozen": True,
    }


def test_save_file_asks_the_app_with_a_complete_request(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        _page(None),
        """
        const save = window.nest.saveFile;
        const results = [];
        results.push(await save({ name: "data.csv", content: "a,b\\n1,2" }));
        results.push(await save({ name: "logo.png", content: "iVBORw0K", encoding: "base64", mime: "image/png" }));
        for (const bad of [undefined, {}, { name: "", content: "x" }, { name: "a", content: 5 },
          { name: "a", content: "x", encoding: "utf16" }]) {
          results.push(await save(bad).then(() => "saved", (e) => e.code + ": " + e.message));
        }
        results.push(await save({ name: "x.txt", content: "x" }).then(() => "saved", (e) => e.code));
        return { results, requests: requests.map((r) => [r.method, r.params]),
          empty: [window.nest.storage.keys(), window.nest.files.list()] };
        """,  # noqa: E501 (embedded JavaScript)
        replies=[
            {"ok": True, "result": {"saved": True}},
            {"ok": True, "result": {"saved": True}},
            {"ok": False, "error": {"code": "declined", "message": "Not saved"}},
        ],
    )

    bad = "bad_request: saveFile needs a name, the content as a string and utf8 or base64"
    assert result == {
        "results": [{"saved": True}, {"saved": True}, bad, bad, bad, bad, bad, "declined"],
        "requests": [
            [
                "saveFile",
                {
                    "name": "data.csv",
                    "content": "a,b\n1,2",
                    "encoding": "utf8",
                    "mime": "application/octet-stream",
                },
            ],
            [
                "saveFile",
                {
                    "name": "logo.png",
                    "content": "iVBORw0K",
                    "encoding": "base64",
                    "mime": "image/png",
                },
            ],
            [
                "saveFile",
                {
                    "name": "x.txt",
                    "content": "x",
                    "encoding": "utf8",
                    "mime": "application/octet-stream",
                },
            ],
        ],
        # Without init data a page starts empty.
        "empty": [[], []],
    }


def test_an_init_element_that_is_not_an_object_gives_an_empty_start(tmp_path: Path) -> None:
    page = _page(None).replace(
        "<script>", '<script type="application/json" id="nest-init">[1, 2]</script><script>', 1
    )
    broken = _page(None).replace(
        "<script>", '<script type="application/json" id="nest-init">{oops</script><script>', 1
    )
    scenario = (
        "return [window.nest.storage.keys(), window.nest.files.list(),"
        " !!document.getElementById('nest-init')];"
    )

    assert run_page(tmp_path, page, scenario) == [[], [], False]
    assert run_page(tmp_path, broken, scenario) == [[], [], True]


def test_init_data_is_escaped_in_the_page(tmp_path: Path) -> None:
    value = "</script><script>window.__ran = 1</script>" + chr(0x2028)
    result = run_page(
        tmp_path,
        _page({"storage": {"v": value}}),
        "return [window.nest.storage.get('v'), window.__ran === undefined];",
    )

    assert result == [value, True]
    assert json.dumps(value) not in _page({"storage": {"v": value}})


# Stage 4: the user's Claude usage, and asking Claude from a page.

_USAGE = {
    "limits": {
        "five_hour": {"utilization": 42, "resets_at": "2026-10-19T15:00:00Z"},
        "seven_day": None,
    },
    "today": {"tokens": 1200, "sessions": 3},
    "week": {"tokens": 9000, "sessions": 11},
}


def test_usage_is_read_through_the_app(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        _page(None),
        "const usage = await window.nest.usage();"
        " return { usage, requests: requests.map((r) => [r.method, r.params]) };",
        replies=[{"ok": True, "result": _USAGE}],
    )

    assert result == {"usage": _USAGE, "requests": [["usage", {}]]}


def test_usage_changes_reach_the_pages_listeners(tmp_path: Path) -> None:
    fresh = {**_USAGE, "today": {"tokens": 1500, "sessions": 4}}
    result = run_page(
        tmp_path,
        _page(None),
        _WAIT
        + f"""
        const host = window.__nestHost;
        const seen = [];
        const off = window.nest.onUsage((usage) => seen.push(usage.today.tokens));
        window.nest.onUsage(() => {{ throw new Error("a listener that fails"); }});
        await wait(10);
        host({{ nest: 1, event: "usage", usage: {json.dumps(fresh)} }});
        host({{ nest: 1, event: "usage", usage: "not usage" }});
        host({{ nest: 1, event: "usage" }});
        host({{ nest: 2, event: "usage", usage: {json.dumps(fresh)} }});
        off();
        host({{ nest: 1, event: "usage", usage: {json.dumps(fresh)} }});
        let bad;
        try {{ window.nest.onUsage("nope"); }} catch (error) {{ bad = error.name; }}
        return {{ seen, bad, requests: requests.map((r) => [r.method, r.params]) }};
        """,
        replies=[{"ok": True, "result": _USAGE}],
    )

    assert result == {
        "seen": [1500],
        "bad": "TypeError",
        # The first listener tells the app this page wants usage updates (one call only).
        "requests": [["usage", {}]],
    }


def test_asking_claude_checks_the_request_in_the_page(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        _page(None),
        """
        const ask = window.nest.ask;
        const outcome = (promise) => promise.then((r) => r, (e) => e.code + ": " + e.message);
        const results = [
          await outcome(ask("A haiku about today")),
          await outcome(ask("Summarise", { system: "Be brief." })),
          await outcome(ask("x".repeat(8000), {})),
        ];
        for (const [prompt, options] of [["", undefined], ["x".repeat(8001), undefined], [5, undefined],
          [undefined, undefined], ["ok", "brief"], ["ok", { system: 5 }], ["ok", { system: "s".repeat(4001) }]]) {
          results.push(await outcome(ask(prompt, options)));
        }
        return { results, requests: requests.map((r) => [r.method, Object.keys(r.params), r.params.system || null]) };
        """,  # noqa: E501 (embedded JavaScript)
        replies=[
            {"ok": True, "result": {"text": "Leaves fall", "remaining": 19}},
            {"ok": True, "result": {"text": "Short.", "remaining": 18}},
            {"ok": True, "result": {"text": "Long.", "remaining": 17}},
        ],
    )

    prompt = "bad_request: ask needs a prompt of 1 to 8,000 characters"
    options = (
        "bad_request: ask's options are an object with an optional system of up to 4,000 characters"
    )
    assert result == {
        "results": [
            {"text": "Leaves fall", "remaining": 19},
            {"text": "Short.", "remaining": 18},
            {"text": "Long.", "remaining": 17},
            prompt,
            prompt,
            prompt,
            prompt,
            options,
            options,
            options,
        ],
        "requests": [
            ["ask", ["prompt"], None],
            ["ask", ["prompt", "system"], "Be brief."],
            ["ask", ["prompt"], None],
        ],
    }


def test_the_apps_ask_errors_reach_the_page(tmp_path: Path) -> None:
    errors = [
        {"code": "budget", "message": "20 asks a day; resets at midnight"},
        {"code": "disabled", "message": "Asking Claude is turned off"},
        {"code": "busy", "message": "Claude is already answering this page"},
        {"code": "unavailable", "message": "Claude did not answer"},
    ]
    result = run_page(
        tmp_path,
        _page(None),
        """
        const results = [];
        for (let i = 0; i < 4; i += 1) {
          results.push(await window.nest.ask("hi").then(() => "answered", (e) => [e.code, e.message]));
        }
        return results;
        """,  # noqa: E501 (embedded JavaScript)
        replies=[{"ok": False, "error": error} for error in errors],
    )

    assert result == [[error["code"], error["message"]] for error in errors]


def test_nest_storage_also_answers_to_the_storage_names(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        _page({"storage": {"a": "1"}}),
        _WAIT
        + """
        const storage = window.nest.storage;
        const returned = storage.setItem("done", true);
        storage.setItem(7, { x: 1 });
        const now = [storage.getItem("done"), storage.getItem("7"), storage.getItem("missing"),
          storage.length, storage.key(0), storage.key(2), storage.key(3), storage.get("done")];
        storage.removeItem("a");
        let refused;
        try { storage.setItem("big", "x".repeat(256 * 1024 + 1)); }
        catch (error) { refused = [error.name, error.message]; }
        await wait(350);
        return { returned: returned === undefined, now, after: [storage.length, storage.keys()], refused,
          frozen: Object.isFrozen(storage), requests: requests.map((r) => [r.method, r.params]) };
        """,  # noqa: E501 (embedded JavaScript)
        replies=[],
    )

    assert result == {
        "returned": True,
        # Values become strings like localStorage's, at once. Keys come in an object's order
        # (integer keys first).
        "now": ["true", "[object Object]", None, 3, "7", "done", None, "true"],
        "after": [2, ["7", "done"]],
        "refused": ["QuotaExceededError", "A value may be at most 256 KiB"],
        "frozen": True,
        "requests": [
            ["storageWrite", {"set": {"done": "true", "7": "[object Object]"}, "remove": ["a"]}]
        ],
    }


def test_an_answer_reads_as_its_text_where_a_string_is_wanted(tmp_path: Path) -> None:
    result = run_page(
        tmp_path,
        _page(None),
        """
        const answer = await window.nest.ask("A haiku");
        const shown = document.createElement("p");
        shown.textContent = answer;
        const odd = await window.nest.ask("Odd");
        return {
          strings: [shown.textContent, String(answer), `${answer}`, answer + "", "> " + answer],
          fields: [answer.text, answer.remaining, answer.limit, Object.keys(answer),
            JSON.stringify(answer)],
          // An answer without text is left as the app sent it.
          odd: [String(odd), Object.keys(odd)],
        };
        """,
        replies=[
            {"ok": True, "result": {"text": "Leaves fall softly", "remaining": 19, "limit": 20}},
            {"ok": True, "result": {"remaining": 18}},
        ],
    )

    assert result == {
        "strings": ["Leaves fall softly"] * 4 + ["> Leaves fall softly"],
        "fields": [
            "Leaves fall softly",
            19,
            20,
            # The text is still a field; toString and toPrimitive are hidden.
            ["text", "remaining", "limit"],
            '{"text":"Leaves fall softly","remaining":19,"limit":20}',
        ],
        "odd": ["[object Object]", ["remaining"]],
    }
