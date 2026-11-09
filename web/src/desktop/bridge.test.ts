// The desktop app's connection to the daemon and the platform: the token reaches the
// daemon as a Bearer header and a socket subprotocol, and a terminal only sees its output.
import { describe, expect, it, vi } from "vitest";
import { HttpApi } from "../api/client.ts";
import { tokenProtocols } from "../api/events.ts";
import { memoryStorage } from "../test/render.tsx";
import {
  browserBridge,
  paneBridge,
  platformBridge,
  ptyId,
  tauriBridge,
  TOKEN_KEY,
  type PaneMessage,
} from "./bridge.ts";

describe("the API client at another origin", () => {
  it("sends the token as a Bearer header to the daemon's address, without cookies", async () => {
    const fetchFn = vi.fn<typeof fetch>(() => Promise.resolve(new Response("[]")));
    const api = new HttpApi(fetchFn, { base: "http://127.0.0.1:8765", token: "secret" });
    await api.repos();
    const [url, init] = fetchFn.mock.calls[0] ?? [];
    expect(url).toBe("http://127.0.0.1:8765/api/repos");
    expect(init?.credentials).toBe("omit");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer secret");
  });

  it("keeps the JSON body type next to the token", async () => {
    const fetchFn = vi.fn<typeof fetch>(() => Promise.resolve(new Response("{}")));
    const api = new HttpApi(fetchFn, { base: "http://127.0.0.1:8765", token: "t" });
    await api.feedback("s1", "again");
    const headers = new Headers(fetchFn.mock.calls[0]?.[1]?.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Authorization")).toBe("Bearer t");
  });

  it("saves the project order and opens a project in an app as the daemon's routes take", async () => {
    const fetchFn = vi.fn<typeof fetch>(() => Promise.resolve(new Response("[]")));
    const api = new HttpApi(fetchFn, { base: "http://127.0.0.1:8765", token: "t" });
    await api.reorderRepos(["b", "a"]);
    await api.openRepo("todo ui", "finder");
    const [order, open] = fetchFn.mock.calls;
    expect(order?.[0]).toBe("http://127.0.0.1:8765/api/repos/order");
    expect(order?.[1]).toMatchObject({ method: "PUT", body: '{"order":["b","a"]}' });
    expect(open?.[0]).toBe("http://127.0.0.1:8765/api/repos/todo%20ui/open");
    expect(open?.[1]).toMatchObject({ method: "POST", body: '{"app":"finder"}' });
  });

  it("names the token in the socket's subprotocols next to nest", () => {
    expect(tokenProtocols("abc")).toEqual(["nest", "nest.token.abc"]);
  });
});

describe("the browser stub", () => {
  it("takes a loopback daemon and its token from the address and remembers them", async () => {
    const storage = memoryStorage();
    const first = browserBridge({ search: "?daemon=http://127.0.0.1:9100/&token=t1" }, storage);
    expect(await first.daemon()).toEqual({ base: "http://127.0.0.1:9100", token: "t1" });
    const later = browserBridge({ search: "" }, storage);
    expect(await later.daemon()).toEqual({ base: "http://127.0.0.1:9100", token: "t1" });
    expect(await browserBridge({ search: "?daemon=http://[::1]:9100" }, null).daemon()).toEqual({
      base: "http://[::1]:9100",
      token: null,
    });
    expect(await browserBridge({ search: "" }, null).daemon()).toEqual({
      base: "http://127.0.0.1:8765",
      token: null,
    });
  });

  it("refuses a daemon that is not on this machine, keeping the token away from it", async () => {
    const storage = memoryStorage();
    browserBridge({ search: "?token=t1" }, storage);
    for (const daemon of [
      "https://evil.example",
      "http://127.0.0.1.evil.example:8765",
      "http://user:pass@localhost:8765",
      "file:///etc/passwd",
      "javascript:alert(1)",
    ]) {
      const bridge = browserBridge({ search: `?daemon=${encodeURIComponent(daemon)}` }, storage);
      await expect(bridge.daemon()).rejects.toThrow("Not a daemon on this machine");
    }
    expect(storage.getItem(TOKEN_KEY)).toContain("t1");
  });

  it("forgets a remembered token when the daemon changes", async () => {
    const storage = memoryStorage();
    browserBridge({ search: "?daemon=http://127.0.0.1:9100&token=t1" }, storage);
    const other = browserBridge({ search: "?daemon=http://localhost:9200" }, storage);
    expect(await other.daemon()).toEqual({ base: "http://localhost:9200", token: null });
    expect(storage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("is not used by a production build outside the desktop app", async () => {
    const bridge = platformBridge({ dev: false, mode: "production" });
    await expect(bridge.daemon()).rejects.toThrow("inside the Nest desktop app");
    expect(platformBridge({ dev: true, mode: "development" }).native).toBe(false);
    await expect(
      platformBridge({ dev: true, mode: "development" }).daemon(),
    ).resolves.toMatchObject({ base: "http://127.0.0.1:8765" });
  });

  it("refuses a terminal, which needs the desktop app", async () => {
    const bridge = browserBridge({ search: "" }, null);
    await expect(
      bridge.spawnPty(
        "t",
        { cwd: null, cols: 80, rows: 24 },
        { onOutput: vi.fn(), onExit: vi.fn() },
      ),
    ).rejects.toThrow("desktop app");
  });
});

/** A fake of Tauri's global API that can fire the events the Rust side emits. */
function fakeTauri() {
  const handlers = new Map<string, (message: { payload: unknown }) => void>();
  const order: string[] = [];
  const invoke = vi.fn((command: string, args?: Record<string, unknown>): Promise<unknown> => {
    order.push(command);
    if (command === "get_daemon") {
      return Promise.resolve({ base_url: "http://127.0.0.1:8765/", token: "local" });
    }
    if (command === "pty_spawn") return Promise.resolve(args?.id);
    if (command === "set_settings") {
      return Promise.resolve({ keep_pill_on_top: false, start_at_login: true });
    }
    return Promise.resolve(null);
  });
  const listen = vi.fn((event: string, handler: (message: { payload: unknown }) => void) => {
    order.push(`listen ${event}`);
    handlers.set(event, handler);
    return Promise.resolve(() => {
      handlers.delete(event);
    });
  });
  const emit = (event: string, payload: unknown) => {
    handlers.get(event)?.({ payload });
  };
  const emitTo = vi.fn((_target: string, event: string, payload?: unknown) => {
    order.push(`emit ${event}`);
    emit(event, payload);
    return Promise.resolve();
  });
  return {
    tauri: { core: { invoke }, event: { listen, emitTo } },
    invoke,
    emit,
    emitTo,
    handlers,
    order,
  };
}

describe("the Tauri bridge", () => {
  it("reads the daemon's address and local token", async () => {
    const { tauri } = fakeTauri();
    expect(await tauriBridge(tauri).daemon()).toEqual({
      base: "http://127.0.0.1:8765",
      token: "local",
    });
  });

  it("listens to a terminal before starting it and stops once it exits", async () => {
    const { tauri, invoke, emit, handlers, order } = fakeTauri();
    const onOutput = vi.fn();
    const onExit = vi.fn();
    const id = ptyId("terminal:5b8f-1");
    expect(id).toBe("terminal-5b8f-1");
    const pty = await tauriBridge(tauri).spawnPty(
      id,
      { cwd: "/repo", cols: 80, rows: 24 },
      { onOutput, onExit },
    );
    expect(order.slice(0, 3)).toEqual([
      `listen pty://${id}`,
      `listen pty://${id}/exit`,
      "pty_spawn",
    ]);
    expect(invoke).toHaveBeenCalledWith("pty_spawn", { id, cwd: "/repo", cols: 80, rows: 24 });
    emit(`pty://${id}`, "$ ");
    expect(onOutput).toHaveBeenCalledExactlyOnceWith("$ ");
    pty.write("ls\r");
    expect(invoke).toHaveBeenCalledWith("pty_write", { id, data: "ls\r" });
    emit(`pty://${id}/exit`, { code: 0 });
    expect(onExit).toHaveBeenCalledWith(0);
    await Promise.resolve();
    expect(handlers.size).toBe(0);
  });

  it("stops listening when the shell cannot start", async () => {
    const { tauri, invoke, handlers } = fakeTauri();
    invoke.mockImplementation((command: string) =>
      command === "pty_spawn"
        ? Promise.reject(new Error("No such folder: /gone"))
        : Promise.resolve(null),
    );
    await expect(
      tauriBridge(tauri).spawnPty(
        "t",
        { cwd: "/gone", cols: 80, rows: 24 },
        { onOutput: vi.fn(), onExit: vi.fn() },
      ),
    ).rejects.toThrow("No such folder");
    await Promise.resolve();
    expect(handlers.size).toBe(0);
  });

  it("sends a pill click to the main window, then brings it forward", async () => {
    const { tauri, emitTo, order } = fakeTauri();
    const bridge = tauriBridge(tauri);
    const asked: unknown[] = [];
    bridge.onOpenRequest((target) => asked.push(target));
    await Promise.resolve();
    await bridge.openInMain({ chat: "s1" });
    expect(emitTo).toHaveBeenCalledWith("main", "nest://open", { chat: "s1" });
    expect(order.slice(-2)).toEqual(["emit nest://open", "show_main"]);
    expect(asked).toEqual([{ chat: "s1" }]);
  });

  // Regression (B157, Ubuntu 26.04): the pill's list stayed open over Nest after the pointer
  // left. The window system's "not over the pill's window" read as "cannot tell", so the
  // check the open list makes never closed it when a leave event went missing.
  it("tells a pointer outside the pill's window from one it cannot find", async () => {
    const { tauri, invoke } = fakeTauri();
    const bridge = tauriBridge(tauri);
    expect(await bridge.pillPointer()).toBe("outside");
    invoke.mockResolvedValueOnce([12, 7]);
    expect(await bridge.pillPointer()).toEqual({ x: 12, y: 7 });
    invoke.mockRejectedValueOnce(new Error("no pill window"));
    expect(await bridge.pillPointer()).toBeNull();
  });

  it("names the chat a notification opens, and no chat when there is none", async () => {
    const { tauri, invoke } = fakeTauri();
    const bridge = tauriBridge(tauri);
    await bridge.notify("todo-ui · Fix the header", "Done.", "s1");
    await bridge.notify("Usage warning", "80% used");
    expect(invoke).toHaveBeenCalledWith("notify", {
      title: "todo-ui · Fix the header",
      body: "Done.",
      chat: "s1",
    });
    expect(invoke).toHaveBeenCalledWith("notify", { title: "Usage warning", body: "80% used" });
  });

  it("saves only the settings that changed, in the Rust names", async () => {
    const { tauri, invoke } = fakeTauri();
    const after = await tauriBridge(tauri).setSettings({ startAtLogin: true });
    expect(invoke).toHaveBeenCalledWith("set_settings", { start_at_login: true });
    expect(after).toEqual({ keepPillOnTop: false, startAtLogin: true });
  });

  it("opens a page in a browser pane's own window, and hears when one closes", async () => {
    const { tauri, invoke, emit } = fakeTauri();
    const bridge = tauriBridge(tauri);
    await bridge.openBrowserWindow("http://localhost:3000");
    await bridge.openBrowserWindow("http://localhost:4000", undefined, "browser-1");
    expect(invoke).toHaveBeenCalledWith("open_browser_window", { url: "http://localhost:3000" });
    expect(invoke).toHaveBeenCalledWith("open_browser_window", {
      url: "http://localhost:4000",
      label: "browser-1",
    });
    const closed: string[] = [];
    bridge.onBrowserClosed((label) => closed.push(label));
    await Promise.resolve();
    emit("nest://browser-closed", "browser-1");
    expect(closed).toEqual(["browser-1"]);
  });
});

describe("a transcript pane in the Mac app", () => {
  const replies = (reply?: unknown) => {
    const sent: PaneMessage[] = [];
    const post = (message: PaneMessage) => {
      sent.push(message);
      return Promise.resolve(reply);
    };
    return { sent, post };
  };

  it("asks the app for the daemon, so nothing in the page holds the token before it", async () => {
    const { sent, post } = replies({ base: "http://127.0.0.1:8765/", token: "secret" });
    const found = await paneBridge(post).daemon();
    expect(found).toEqual({ base: "http://127.0.0.1:8765", token: "secret" });
    expect(sent).toEqual([{ kind: "daemon" }]);
  });

  it("is used in a production build only where the app's handler exists", async () => {
    const build = { dev: false, mode: "production" };
    await expect(platformBridge(build).daemon()).rejects.toThrow("runs inside");
    const postMessage = vi.fn(() => Promise.resolve({ base: "http://127.0.0.1:1", token: "t" }));
    window.webkit = { messageHandlers: { nestPane: { postMessage } } };
    try {
      await expect(platformBridge(build).daemon()).resolves.toMatchObject({ token: "t" });
    } finally {
      delete window.webkit;
    }
  });

  it("names a file by its path alone: the app holds the chat's folder", async () => {
    const { sent, post } = replies();
    await paneBridge(post).openTextFile("Sources/App.swift", "/tmp/somewhere-else");
    expect(sent).toEqual([{ kind: "openFile", path: "Sources/App.swift" }]);
  });
});
