import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BridgeError,
  admit,
  useArtifactBridge,
  type Handlers,
  checkLink,
  fail,
  linkMessage,
  rateWindow,
  succeed,
  MAX_REQUEST_BYTES,
  MAX_SAVE_BYTES,
  MAX_STORAGE_BYTES,
  MAX_FILE_BYTES,
  MAX_ASK_BYTES,
  PRINT,
  storageEvents,
} from "./bridge.ts";

const always = () => true;
const anyText = expect.any(String) as string;

describe("rateWindow", () => {
  it("allows 30 requests in any 10 s and frees slots as they age out", () => {
    let time = 0;
    const allow = rateWindow(() => time);
    for (let i = 0; i < 30; i++) {
      time = i * 100;
      expect(allow()).toBe(true);
    }
    expect(allow()).toBe(false);
    // The first request was at 0; at 10 s it no longer counts, the second still does.
    time = 10_000;
    expect(allow()).toBe(true);
    expect(allow()).toBe(false);
    time = 20_000;
    expect(allow()).toBe(true);
  });

  it("does not count refused requests", () => {
    let time = 0;
    const allow = rateWindow(() => time, 1, 1000);
    expect(allow()).toBe(true);
    time = 500;
    expect(allow()).toBe(false);
    time = 1000;
    expect(allow()).toBe(true);
  });
});

describe("admit", () => {
  const request = { nest: 1, id: "1-ab", method: "openLink", params: { url: "https://a.dev" } };

  it("reads a well formed request for a known method", () => {
    expect(admit(request, always)).toEqual({
      call: { id: "1-ab", method: "openLink", args: { url: "https://a.dev/" } },
    });
  });

  it.each([
    ["not an object", "hello"],
    ["null", null],
    ["an array", [1]],
    ["no id", { nest: 1, method: "openLink", params: {} }],
    ["a number id", { ...request, id: 7 }],
    ["an empty id", { ...request, id: "" }],
    ["an id over 64 characters", { ...request, id: "x".repeat(65) }],
  ])("ignores a message with %s", (_, data) => {
    expect(admit(data, always)).toBeNull();
  });

  it("takes an id of exactly 64 characters", () => {
    expect(admit({ ...request, id: "x".repeat(64) }, always)).toHaveProperty("call");
  });

  it.each([
    ["the wrong version", { ...request, nest: 2 }],
    ["no method", { ...request, method: undefined }],
    ["params that are not an object", { ...request, params: "x" }],
    ["params that are an array", { ...request, params: [] }],
    ["params that are null", { ...request, params: null }],
    ["params that are not a plain object", { ...request, params: new Date() }],
  ])("answers bad_request to %s", (_, data) => {
    expect(admit(data, always)).toEqual({ reply: fail("1-ab", "bad_request", anyText) });
  });

  it("takes params without a prototype", () => {
    const params = Object.assign(Object.create(null) as object, { url: "https://a.dev" });
    expect(admit({ ...request, params }, always)).toHaveProperty("call");
  });

  it("answers too_large over 64 KiB, counting bytes rather than characters", () => {
    const empty = { ...request, params: { url: "https://a.dev", pad: "" } };
    const room = MAX_REQUEST_BYTES - JSON.stringify(empty).length;
    const at = { ...request, params: { url: "https://a.dev", pad: "a".repeat(room) } };
    expect(admit(at, always)).toHaveProperty("call");
    const over = { ...request, params: { url: "https://a.dev", pad: "a".repeat(room + 1) } };
    expect(admit(over, always)).toEqual({ reply: fail("1-ab", "too_large", anyText) });
    // One character, two bytes.
    const wide = {
      ...request,
      params: { url: "https://a.dev", pad: "é".repeat(Math.floor(room / 2) + 1) },
    };
    expect(admit(wide, always)).toEqual({ reply: fail("1-ab", "too_large", anyText) });
  });

  it("answers bad_request to params that cannot be written as JSON", () => {
    const params: Record<string, unknown> = { url: "https://a.dev" };
    params.self = params;
    expect(admit({ ...request, params }, always)).toEqual({
      reply: fail("1-ab", "bad_request", anyText),
    });
  });

  it("answers rate_limited when the window is full, before reading the rest", () => {
    expect(admit({ id: "9", nest: 3 }, () => false)).toEqual({
      reply: fail("9", "rate_limited", anyText),
    });
  });

  it.each(["fetch", "toString", "__proto__", "constructor"])(
    "answers unknown_method to %s",
    (method) => {
      expect(admit({ ...request, method }, always)).toEqual({
        reply: fail("1-ab", "unknown_method", anyText),
      });
    },
  );

  it("answers bad_request when a method's params do not check", () => {
    expect(admit({ ...request, params: { url: "javascript:alert(1)" } }, always)).toEqual({
      reply: fail("1-ab", "bad_request", anyText),
    });
  });
});

describe("admit saveDocument", () => {
  const save = (params: unknown) => ({ nest: 1, id: "s", method: "saveDocument", params });

  it("reads the content and the version it was edited from", () => {
    expect(admit(save({ content: "# Plan\n", base_version: 3 }), always)).toEqual({
      call: { id: "s", method: "saveDocument", args: { content: "# Plan\n", base_version: 3 } },
    });
  });

  it("takes empty content, which the Mac then checks", () => {
    expect(admit(save({ content: "", base_version: 1 }), always)).toHaveProperty("call");
  });

  it.each([
    ["no content", { base_version: 1 }],
    ["content that is not text", { content: 5, base_version: 1 }],
    ["no base version", { content: "x" }],
    ["a base version as text", { content: "x", base_version: "1" }],
    ["a fractional base version", { content: "x", base_version: 1.5 }],
    ["a zero base version", { content: "x", base_version: 0 }],
    ["a negative base version", { content: "x", base_version: -2 }],
    ["a base version that is not finite", { content: "x", base_version: Infinity }],
  ])("answers bad_request to %s", (_, params) => {
    expect(admit(save(params), always)).toEqual({ reply: fail("s", "bad_request", anyText) });
  });

  it("allows 1 MiB and 1 KiB for a save, while other methods keep 64 KiB", () => {
    expect(MAX_SAVE_BYTES).toBe(1024 * 1024 + 1024);
    const empty = save({ content: "", base_version: 1 });
    const room = MAX_SAVE_BYTES - JSON.stringify(empty).length;
    expect(admit(save({ content: "a".repeat(room), base_version: 1 }), always)).toHaveProperty(
      "call",
    );
    expect(admit(save({ content: "a".repeat(room + 1), base_version: 1 }), always)).toEqual({
      reply: fail("s", "too_large", "The request is over 1025 KiB."),
    });
    const link = { nest: 1, id: "l", method: "openLink", params: { url: "https://a.dev" } };
    const big = { ...link, params: { url: "https://a.dev", pad: "a".repeat(MAX_REQUEST_BYTES) } };
    expect(admit(big, always)).toEqual({
      reply: fail("l", "too_large", "The request is over 64 KiB."),
    });
  });

  it("keeps an unknown method to 64 KiB", () => {
    const big = { nest: 1, id: "u", method: "x", params: { pad: "a".repeat(MAX_REQUEST_BYTES) } };
    expect(admit(big, always)).toEqual({ reply: fail("u", "too_large", anyText) });
  });
});

describe("admit storageWrite and storageClear (B88)", () => {
  const write = (params: unknown) => ({ nest: 1, id: "w", method: "storageWrite", params });

  it("reads the keys to set and to remove", () => {
    expect(admit(write({ set: { a: "1", b: "" }, remove: ["c"] }), always)).toEqual({
      call: { id: "w", method: "storageWrite", args: { set: { a: "1", b: "" }, remove: ["c"] } },
    });
  });

  it("takes either part alone", () => {
    expect(admit(write({ set: { a: "1" } }), always)).toEqual({
      call: { id: "w", method: "storageWrite", args: { set: { a: "1" }, remove: [] } },
    });
    expect(admit(write({ remove: ["a"] }), always)).toEqual({
      call: { id: "w", method: "storageWrite", args: { set: {}, remove: ["a"] } },
    });
  });

  it("takes a key of 256 characters", () => {
    expect(admit(write({ set: { ["k".repeat(256)]: "v" } }), always)).toHaveProperty("call");
  });

  it.each([
    ["set that is not an object", { set: ["a"] }],
    ["a value that is not text", { set: { a: 1 } }],
    ["an empty key", { set: { "": "v" } }],
    ["a key over 256 characters", { set: { ["k".repeat(257)]: "v" } }],
    ["remove that is not a list", { remove: "a" }],
    ["a removed key that is not text", { remove: [1] }],
    ["an empty removed key", { remove: [""] }],
    ["a removed key over 256 characters", { remove: ["k".repeat(257)] }],
  ])("answers bad_request to %s", (_, params) => {
    expect(admit(write(params), always)).toEqual({ reply: fail("w", "bad_request", anyText) });
  });

  it("allows 2 MiB and 4 KiB for a write", () => {
    expect(MAX_STORAGE_BYTES).toBe(2 * 1024 * 1024 + 4096);
    const empty = write({ set: { a: "" } });
    const room = MAX_STORAGE_BYTES - JSON.stringify(empty).length;
    expect(admit(write({ set: { a: "x".repeat(room) } }), always)).toHaveProperty("call");
    expect(admit(write({ set: { a: "x".repeat(room + 1) } }), always)).toEqual({
      reply: fail("w", "too_large", "The request is over 2052 KiB."),
    });
  });

  it("reads a clear, which takes nothing", () => {
    expect(admit({ nest: 1, id: "c", method: "storageClear", params: {} }, always)).toEqual({
      call: { id: "c", method: "storageClear", args: {} },
    });
  });
});

describe("admit saveFile (B88)", () => {
  const save = (params: unknown) => ({ nest: 1, id: "f", method: "saveFile", params });

  it("reads a text file, utf8 and a generic type unless given", () => {
    expect(admit(save({ name: "data.csv", content: "a,b\n" }), always)).toEqual({
      call: {
        id: "f",
        method: "saveFile",
        args: { name: "data.csv", content: "a,b\n", encoding: "utf8" },
      },
    });
  });

  it("reads a base64 file and makes its name safe", () => {
    expect(
      admit(
        save({ name: "../logo:1.png", content: "iVBORw0KGgo=", encoding: "base64", mime: "x" }),
        always,
      ),
    ).toEqual({
      call: {
        id: "f",
        method: "saveFile",
        args: { name: "logo 1.png", content: "iVBORw0KGgo=", encoding: "base64" },
      },
    });
  });

  it.each([
    ["no name", { content: "x" }],
    ["a name that is only unsafe characters", { name: "/// ", content: "x" }],
    ["content that is not text", { name: "a.txt", content: 3 }],
    ["an unknown encoding", { name: "a.txt", content: "x", encoding: "hex" }],
    ["base64 that is not", { name: "a.png", content: "abc!", encoding: "base64" }],
    ["base64 of the wrong length", { name: "a.png", content: "abc", encoding: "base64" }],
  ])("answers bad_request to %s", (_, params) => {
    expect(admit(save(params), always)).toEqual({ reply: fail("f", "bad_request", anyText) });
  });

  it("allows 24 MiB for a file", () => {
    expect(MAX_FILE_BYTES).toBe(24 * 1024 * 1024);
    const empty = save({ name: "a.txt", content: "" });
    const room = MAX_FILE_BYTES - JSON.stringify(empty).length;
    expect(admit(save({ name: "a.txt", content: "x".repeat(room) }), always)).toHaveProperty(
      "call",
    );
    expect(admit(save({ name: "a.txt", content: "x".repeat(room + 1) }), always)).toEqual({
      reply: fail("f", "too_large", "The request is over 24576 KiB."),
    });
  });
});

describe("admit usage and ask (B88)", () => {
  const ask = (params: unknown) => ({ nest: 1, id: "q", method: "ask", params });

  it("reads a usage request, which takes nothing", () => {
    expect(admit({ nest: 1, id: "u", method: "usage", params: {} }, always)).toEqual({
      call: { id: "u", method: "usage", args: {} },
    });
  });

  it("reads a prompt, with a system text when given", () => {
    expect(admit(ask({ prompt: "A haiku" }), always)).toEqual({
      call: { id: "q", method: "ask", args: { prompt: "A haiku" } },
    });
    expect(admit(ask({ prompt: "A haiku", system: "Be brief" }), always)).toEqual({
      call: { id: "q", method: "ask", args: { prompt: "A haiku", system: "Be brief" } },
    });
  });

  it("takes a prompt of 8,000 characters and a system text of 4,000", () => {
    expect(
      admit(ask({ prompt: "p".repeat(8000), system: "s".repeat(4000) }), always),
    ).toHaveProperty("call");
  });

  it.each([
    ["no prompt", {}],
    ["an empty prompt", { prompt: "" }],
    ["a prompt over 8,000 characters", { prompt: "p".repeat(8001) }],
    ["a prompt that is not text", { prompt: 5 }],
    ["a system text that is not text", { prompt: "a", system: 5 }],
    ["a system text over 4,000 characters", { prompt: "a", system: "s".repeat(4001) }],
  ])("answers bad_request to %s", (_, params) => {
    expect(admit(ask(params), always)).toEqual({ reply: fail("q", "bad_request", anyText) });
  });

  it("keeps an ask to 16 KiB", () => {
    expect(MAX_ASK_BYTES).toBe(16 * 1024);
    const big = ask({ prompt: "a", system: "é".repeat(4000), pad: "x".repeat(10_000) });
    expect(admit(big, always)).toEqual({
      reply: fail("q", "too_large", "The request is over 16 KiB."),
    });
  });
});

describe("storageEvents", () => {
  it("are one host event per key set or removed", () => {
    expect(storageEvents({ set: { a: "1", b: "2" }, remove: ["c"], clear: false })).toEqual([
      { nest: 1, event: "storage", key: "a", value: "1" },
      { nest: 1, event: "storage", key: "b", value: "2" },
      { nest: 1, event: "storage", key: "c", value: null },
    ]);
  });

  it("are a single clear, then any keys set after it", () => {
    expect(storageEvents({ set: {}, remove: [], clear: true })).toEqual([
      { nest: 1, event: "storage", clear: true },
    ]);
    expect(storageEvents({ set: { a: "1" }, remove: [], clear: true })).toEqual([
      { nest: 1, event: "storage", clear: true },
      { nest: 1, event: "storage", key: "a", value: "1" },
    ]);
  });
});

describe("the print event", () => {
  it("is the host event the shim prints on", () => {
    expect(PRINT).toEqual({ nest: 1, event: "print" });
  });
});

describe("checkLink", () => {
  it.each([
    ["https://example.com/a?b=1#c", "https://example.com/a?b=1#c"],
    ["http://example.com", "http://example.com/"],
    ["HTTPS://Example.com/", "https://example.com/"],
    ["mailto:me@example.com", "mailto:me@example.com"],
  ])("takes %s, as the address that opens", (url, opens) => {
    expect(checkLink(url)).toBe(opens);
  });

  it.each([
    ["javascript:", "javascript:alert(1)"],
    ["javascript: in capitals", "JavaScript:alert(1)"],
    ["data:", "data:text/html,<script>alert(1)</script>"],
    ["file:", "file:///tmp/x.command"],
    ["an app scheme", "vscode://file/a"],
    ["a relative path", "/next"],
    ["a fragment", "#top"],
    ["a scheme-relative link", "//example.com"],
    ["http without slashes", "http:example.com"],
    ["a broken URL", "https://"],
    ["empty", ""],
    ["not a string", 42],
    ["missing", undefined],
  ])("refuses %s", (_, url) => {
    expect(checkLink(url)).toBeNull();
  });

  it("takes 2,048 characters and no more", () => {
    const base = "https://example.com/";
    expect(checkLink(base + "a".repeat(2048 - base.length))).not.toBeNull();
    expect(checkLink(base + "a".repeat(2049 - base.length))).toBeNull();
  });
});

describe("linkMessage", () => {
  it("is the URL when it is short", () => {
    expect(linkMessage("https://example.com/a")).toBe("https://example.com/a");
  });

  it("puts the host first when it is long", () => {
    const url = `https://docs.example.com/${"a".repeat(80)}`;
    expect(linkMessage(url)).toBe(`docs.example.com\n${url}`);
  });

  it("has no host line for a long mail link", () => {
    const url = `mailto:${"a".repeat(80)}@example.com`;
    expect(linkMessage(url)).toBe(url);
  });
});

describe("replies", () => {
  it("carry the protocol version and id", () => {
    expect(succeed("4", { opened: true })).toEqual({
      nest: 1,
      id: "4",
      ok: true,
      result: { opened: true },
    });
    expect(fail("4", "declined", "No")).toEqual({
      nest: 1,
      id: "4",
      ok: false,
      error: { code: "declined", message: "No" },
    });
  });

  it("BridgeError keeps its code", () => {
    const error = new BridgeError("busy", "Busy");
    expect(error).toBeInstanceOf(Error);
    expect(error.code).toBe("busy");
    expect(error.message).toBe("Busy");
  });
});

describe("useArtifactBridge", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  /** A frame in the document, the bridge on it, and a way to post as its page. */
  function mounted(given: Partial<Handlers>) {
    const handlers: Handlers = {
      openLink: () => Promise.resolve({ opened: true }),
      saveDocument: () => Promise.resolve({ version: 2 }),
      storageWrite: () => Promise.resolve({ size: 0 }),
      storageClear: () => Promise.resolve({ size: 0 }),
      saveFile: () => Promise.resolve({ saved: true }),
      usage: () => Promise.resolve({}),
      ask: () => Promise.resolve({ text: "", remaining: 1 }),
      ...given,
    };
    const frame = document.createElement("iframe");
    document.body.append(frame);
    const page = frame.contentWindow;
    if (page === null) throw new Error("no window");
    const sent = vi.spyOn(page, "postMessage");
    const ref = { current: frame as HTMLIFrameElement | null };
    const hook = renderHook(() => {
      useArtifactBridge(ref, handlers);
    });
    const post = (data: unknown) => {
      act(() => {
        window.dispatchEvent(new MessageEvent("message", { data, source: page }));
      });
    };
    return { ref, sent, hook, post };
  }

  const call = { nest: 1, id: "1", method: "openLink", params: { url: "https://a.dev" } };

  it("answers unavailable when a handler fails for a reason of its own", async () => {
    const { sent, post } = mounted({ openLink: () => Promise.reject(new Error("boom")) });
    post(call);
    await waitFor(() => {
      expect(sent).toHaveBeenCalledWith(fail("1", "unavailable", "Nest could not do that."), "*");
    });
  });

  it("answers with a handler's own refusal, thrown or rejected", async () => {
    const { sent, post } = mounted({
      openLink: () => {
        throw new BridgeError("busy", "Busy");
      },
    });
    post(call);
    await waitFor(() => {
      expect(sent).toHaveBeenCalledWith(fail("1", "busy", "Busy"), "*");
    });
  });

  it("ignores messages while it has no frame", async () => {
    const openLink = vi.fn(() => Promise.resolve({ opened: true }));
    const { ref, sent, post } = mounted({ openLink });
    ref.current = null;
    post(call);
    await act(() => Promise.resolve());
    expect(openLink).not.toHaveBeenCalled();
    expect(sent).not.toHaveBeenCalled();
  });

  it("drops a reply that comes after it unmounts", async () => {
    let finish: (result: unknown) => void = () => undefined;
    const { sent, hook, post } = mounted({
      openLink: () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    });
    post(call);
    hook.unmount();
    finish({ opened: true });
    await act(() => Promise.resolve());
    expect(sent).not.toHaveBeenCalled();
  });
});
