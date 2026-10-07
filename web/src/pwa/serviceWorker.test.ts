import { describe, expect, it, vi } from "vitest";
import { defined } from "../test/defined.ts";
import {
  CACHE,
  ICON,
  installWorker,
  NAVIGATE,
  parsePush,
  respond,
  SHELL,
  type WindowClientLike,
  type WorkerScope,
} from "./serviceWorker.ts";

/** In-memory Cache Storage keyed by URL path. */
function fakeCaches() {
  const stores = new Map<string, Map<string, Response>>();
  const key = (request: RequestInfo | URL) =>
    typeof request === "string" ? request : new URL((request as Request).url).pathname;
  const open = (name: string) => {
    const store = stores.get(name) ?? new Map<string, Response>();
    stores.set(name, store);
    return Promise.resolve({
      addAll: (paths: string[]) => {
        for (const p of paths) store.set(p, new Response(`cached ${p}`));
        return Promise.resolve();
      },
      put: (request: RequestInfo | URL, response: Response) => {
        store.set(key(request), response);
        return Promise.resolve();
      },
      match: (request: RequestInfo | URL) => Promise.resolve(store.get(key(request))),
    } as unknown as Cache);
  };
  const caches = {
    open,
    keys: () => Promise.resolve([...stores.keys()]),
    delete: (name: string) => Promise.resolve(stores.delete(name)),
  } as unknown as CacheStorage;
  return { caches, stores };
}

function setup(fetch: WorkerScope["fetch"] = () => Promise.resolve(new Response("network"))) {
  const { caches, stores } = fakeCaches();
  const listeners = new Map<string, (event: never) => void>();
  const claim = vi.fn(() => Promise.resolve());
  const skipWaiting = vi.fn(() => Promise.resolve());
  const network = vi.fn(fetch);
  const windows: WindowClientLike[] = [];
  const matchAll = vi.fn(() => Promise.resolve(windows));
  const openWindow = vi.fn(() => Promise.resolve(null));
  const showNotification = vi.fn(() => Promise.resolve());
  const scope = {
    location: { origin: "https://mac.ts.net" },
    caches,
    clients: { claim, matchAll, openWindow },
    registration: { showNotification },
    skipWaiting,
    fetch: network,
    addEventListener: (type: string, listener: (event: never) => void) => {
      listeners.set(type, listener);
    },
  } as unknown as WorkerScope;
  return {
    scope,
    stores,
    listeners,
    claim,
    skipWaiting,
    network,
    windows,
    matchAll,
    openWindow,
    showNotification,
  };
}

const get = (path: string, mode: RequestMode = "cors") => {
  const request = new Request(`https://mac.ts.net${path}`);
  Object.defineProperty(request, "mode", { value: mode });
  return request;
};

describe("service worker", () => {
  it("precaches the shell on install and drops old caches on activate", async () => {
    const { scope, stores, listeners, claim, skipWaiting } = setup();
    installWorker(scope);
    await scope.caches.open("harness-shell-v0");

    let pending: Promise<unknown> = Promise.resolve();
    const waitUntil = (p: Promise<unknown>) => {
      pending = p;
    };
    listeners.get("install")?.({ waitUntil } as never);
    await pending;
    listeners.get("activate")?.({ waitUntil } as never);
    await pending;

    expect([...stores.keys()]).toEqual([CACHE]);
    expect([...(stores.get(CACHE)?.keys() ?? [])]).toEqual(SHELL);
    expect(skipWaiting).toHaveBeenCalled();
    expect(claim).toHaveBeenCalled();
  });

  it("answers only shell requests from its fetch listener", async () => {
    const { scope, listeners } = setup();
    installWorker(scope);
    const respondWith = vi.fn();

    listeners.get("fetch")?.({ request: get("/api/sessions"), respondWith } as never);
    expect(respondWith).not.toHaveBeenCalled();
    listeners.get("fetch")?.({ request: get("/assets/a.js"), respondWith } as never);
    expect(await (respondWith.mock.calls[0]?.[0] as Promise<Response>)).toBeInstanceOf(Response);
  });

  it("leaves the API, other origins and non-GET requests to the network", () => {
    const { scope } = setup();

    expect(respond(scope, get("/api/repos"))).toBeNull();
    expect(respond(scope, new Request("https://elsewhere.dev/assets/a.js"))).toBeNull();
    expect(respond(scope, new Request("https://mac.ts.net/x", { method: "POST" }))).toBeNull();
    expect(respond(scope, get("/favicon.ico"))).toBeNull();
  });

  it("serves pages network first and falls back to the cached shell offline", async () => {
    const { scope, network } = setup();
    expect(await (await defined(respond(scope, get("/projects", "navigate")))).text()).toBe(
      "network",
    );

    network.mockRejectedValue(new TypeError("offline"));
    const offline = await defined(respond(scope, get("/inbox", "navigate")));
    expect(await offline.text()).toBe("network");
    const missing = await defined(respond(scope, get("/icon-512.png")));
    expect(missing.type).toBe("error");
  });

  it("does not cache failed responses", async () => {
    const { scope, stores } = setup(() => Promise.resolve(new Response("nope", { status: 500 })));

    await respond(scope, get("/manifest.webmanifest"));
    await respond(scope, get("/assets/b.js"));

    expect(stores.get(CACHE)?.size).toBe(0);
  });

  it("serves hashed assets from the cache once fetched", async () => {
    const { scope, network } = setup();

    await respond(scope, get("/assets/a.js"));
    network.mockRejectedValue(new TypeError("offline"));
    const cached = await defined(respond(scope, get("/assets/a.js")));

    expect(await cached.text()).toBe("network");
    expect(network).toHaveBeenCalledTimes(1);
  });
});

/** Fire a listener and wait for what it passed to waitUntil. */
async function fire(listener: ((event: never) => void) | undefined, event: object) {
  let pending: Promise<unknown> = Promise.resolve();
  listener?.({ ...event, waitUntil: (p: Promise<unknown>) => (pending = p) } as never);
  await pending;
}

const pushData = (value: unknown) => ({ json: () => value });

function windowClient(url: string) {
  return { url, focus: vi.fn(() => Promise.resolve()), postMessage: vi.fn() };
}

describe("push notifications", () => {
  it("shows the daemon's notification with its tag, icon and link", async () => {
    const { scope, listeners, showNotification } = setup();
    installWorker(scope);

    await fire(listeners.get("push"), {
      data: pushData({
        title: "Needs approval · harness",
        body: "Fix: Bash",
        url: "/inbox",
        tag: "s1",
      }),
    });

    expect(showNotification).toHaveBeenCalledWith("Needs approval · harness", {
      body: "Fix: Bash",
      icon: ICON,
      tag: "s1",
      data: { url: "/inbox" },
    });
  });

  it("still shows something for empty or unreadable pushes", async () => {
    const { scope, listeners, showNotification } = setup();
    installWorker(scope);
    await fire(listeners.get("push"), { data: null });
    expect(showNotification).toHaveBeenCalledWith("harness", {
      body: "",
      icon: ICON,
      data: { url: "/inbox" },
    });

    expect(parsePush(null)).toEqual({ title: "harness", body: "", url: "/inbox" });
    expect(
      parsePush({
        json: () => {
          throw new SyntaxError("not json");
        },
      }),
    ).toEqual({ title: "harness", body: "", url: "/inbox" });
    expect(parsePush(pushData("text"))).toEqual({ title: "harness", body: "", url: "/inbox" });
    expect(parsePush(pushData({ title: 3, url: "https://evil.example/x" }))).toEqual({
      title: "harness",
      body: "",
      url: "/inbox",
    });
    expect(parsePush(pushData({ url: "//evil.example/x" })).url).toBe("/inbox");
  });

  it("focuses an open window and sends it to the item", async () => {
    const { scope, listeners, windows, openWindow } = setup();
    installWorker(scope);
    const other = windowClient("https://elsewhere.dev/");
    const app = windowClient("https://mac.ts.net/projects");
    windows.push(other, app);
    const close = vi.fn();

    await fire(listeners.get("notificationclick"), {
      notification: { data: { url: "/chat/s%2F1" }, close },
    });

    expect(close).toHaveBeenCalled();
    expect(app.focus).toHaveBeenCalled();
    expect(app.postMessage).toHaveBeenCalledWith({ type: NAVIGATE, url: "/chat/s%2F1" });
    expect(other.focus).not.toHaveBeenCalled();
    expect(openWindow).not.toHaveBeenCalled();
  });

  it("opens the app at the item when no window is open", async () => {
    const { scope, listeners, openWindow } = setup();
    installWorker(scope);

    await fire(listeners.get("notificationclick"), {
      notification: { data: null, close: vi.fn() },
    });

    expect(openWindow).toHaveBeenCalledWith("/inbox");
  });
});
