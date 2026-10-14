import { describe, expect, it, vi } from "vitest";
import { defined } from "../test/defined.ts";
import {
  CACHE,
  ICON,
  installWorker,
  NAVIGATE,
  NAVIGATION_TIMEOUT_MS,
  parsePush,
  respond,
  SHELL,
  type WindowClientLike,
  type WorkerScope,
} from "./serviceWorker.ts";

/** In-memory Cache Storage keyed by URL path; `addAll` stores what `served` gives. */
function fakeCaches(served: (path: string) => string = (path) => `cached ${path}`) {
  const stores = new Map<string, Map<string, Response>>();
  const key = (request: RequestInfo | URL) =>
    typeof request === "string" ? request : new URL((request as Request).url).pathname;
  const open = (name: string) => {
    const store = stores.get(name) ?? new Map<string, Response>();
    stores.set(name, store);
    return Promise.resolve({
      addAll: (paths: string[]) => {
        for (const p of paths) store.set(p, new Response(served(p)));
        return Promise.resolve();
      },
      put: (request: RequestInfo | URL, response: Response) => {
        store.set(key(request), response);
        return Promise.resolve();
      },
      match: (request: RequestInfo | URL) => Promise.resolve(store.get(key(request))),
      keys: () =>
        Promise.resolve([...store.keys()].map((path) => new Request(`https://mac.ts.net${path}`))),
      delete: (request: RequestInfo | URL) => Promise.resolve(store.delete(key(request))),
    } as unknown as Cache);
  };
  const caches = {
    open,
    keys: () => Promise.resolve([...stores.keys()]),
    delete: (name: string) => Promise.resolve(stores.delete(name)),
  } as unknown as CacheStorage;
  return { caches, stores };
}

function setup(
  fetch: WorkerScope["fetch"] = () => Promise.resolve(new Response("network")),
  served?: (path: string) => string,
) {
  const { caches, stores } = fakeCaches(served);
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

  it("precaches the assets the cached page names, so the next launch works offline", async () => {
    const page = '<script src="/assets/index-a.js"></script><link href="/assets/index-a.css">';
    const { scope, stores, listeners } = setup(undefined, (path) =>
      path === "/" ? page : `cached ${path}`,
    );
    installWorker(scope);

    let pending: Promise<unknown> = Promise.resolve();
    listeners.get("install")?.({
      waitUntil: (p: Promise<unknown>) => {
        pending = p;
      },
    } as never);
    await pending;

    expect([...(stores.get(CACHE)?.keys() ?? [])]).toEqual([
      ...SHELL,
      "/assets/index-a.js",
      "/assets/index-a.css",
    ]);
  });

  it("still installs when the cached page is gone before its assets are read", async () => {
    const page = '<script src="/assets/index-a.js"></script>';
    const { scope, stores, listeners } = setup(undefined, (path) =>
      path === "/" ? page : `cached ${path}`,
    );
    const open = scope.caches.open.bind(scope.caches);
    // Storage pressure, say, between caching the shell and reading the page back.
    scope.caches.open = async (name) => {
      const cache = await open(name);
      cache.match = () => Promise.resolve(undefined);
      return cache;
    };
    installWorker(scope);

    let pending: Promise<unknown> = Promise.resolve();
    listeners.get("install")?.({
      waitUntil: (p: Promise<unknown>) => {
        pending = p;
      },
    } as never);
    await pending;

    expect([...(stores.get(CACHE)?.keys() ?? [])]).toEqual(SHELL);
  });

  it("keeps the worker alive until a late page has refreshed the cache", async () => {
    vi.useFakeTimers();
    try {
      let answer: (response: Response) => void = () => undefined;
      const { scope, stores, listeners } = setup(
        () =>
          new Promise((resolve) => {
            answer = resolve;
          }),
      );
      await (await scope.caches.open(CACHE)).put("/", new Response("old page"));
      installWorker(scope);
      const respondWith = vi.fn();
      const waitUntil = vi.fn();

      listeners.get("fetch")?.({
        request: get("/inbox", "navigate"),
        respondWith,
        waitUntil,
      } as never);
      // Held from the start, while the fetch event is still being dispatched.
      expect(waitUntil).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(NAVIGATION_TIMEOUT_MS);
      expect(
        await (respondWith.mock.calls[0]?.[0] as Promise<Response>).then((r) => r.text()),
      ).toBe("old page");
      let held = false;
      void (waitUntil.mock.calls[0]?.[0] as Promise<unknown>).then(() => (held = true));
      await vi.advanceTimersByTimeAsync(0);
      expect(held).toBe(false);

      answer(new Response("newer page"));
      await vi.advanceTimersByTimeAsync(0);
      expect(held).toBe(true);
      expect(await stores.get(CACHE)?.get("/")?.text()).toBe("newer page");
    } finally {
      vi.useRealTimers();
    }
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

  it("falls back to the cached shell when the Mac answers with a server error", async () => {
    const { scope, network } = setup(() =>
      Promise.resolve(new Response("bad gateway", { status: 502 })),
    );
    // Nothing cached yet: the error is all there is.
    const first = await defined(respond(scope, get("/inbox", "navigate")));
    expect(first.status).toBe(502);

    await (await scope.caches.open(CACHE)).put("/", new Response("shell"));
    const page = await defined(respond(scope, get("/inbox", "navigate")));

    expect(await page.text()).toBe("shell");
    expect(network).toHaveBeenCalledTimes(2);
  });

  it("falls back to the cached shell when the Mac is slow to answer", async () => {
    vi.useFakeTimers();
    try {
      let answer: (response: Response) => void = () => undefined;
      const { scope, stores } = setup(
        () =>
          new Promise((resolve) => {
            answer = resolve;
          }),
      );
      // Nothing cached: it waits for the network.
      const waiting = defined(respond(scope, get("/inbox", "navigate")));
      await vi.advanceTimersByTimeAsync(NAVIGATION_TIMEOUT_MS);
      answer(new Response("late page"));
      expect(await (await waiting).text()).toBe("late page");

      const slow = defined(respond(scope, get("/inbox", "navigate")));
      await vi.advanceTimersByTimeAsync(NAVIGATION_TIMEOUT_MS - 1);
      let settled = false;
      void slow.then(() => (settled = true));
      await vi.advanceTimersByTimeAsync(0);
      expect(settled).toBe(false);
      await vi.advanceTimersByTimeAsync(1);

      expect(await (await slow).text()).toBe("late page");
      // The page that comes later still refreshes the cache.
      answer(new Response("newer page"));
      await vi.advanceTimersByTimeAsync(0);
      expect(await stores.get(CACHE)?.get("/")?.text()).toBe("newer page");
    } finally {
      vi.useRealTimers();
    }
  });

  it("drops cached assets the newest page no longer uses", async () => {
    const page = '<script src="/assets/index-new.js"></script><link href="/assets/index-new.css">';
    const { scope, stores, network } = setup(() => Promise.resolve(new Response(page)));
    const cache = await scope.caches.open(CACHE);
    for (const path of ["/assets/index-old.js", "/assets/index-new.js", "/icon-192.png"]) {
      await cache.put(path, new Response(path));
    }

    await defined(respond(scope, get("/projects", "navigate")));
    expect([...(stores.get(CACHE)?.keys() ?? [])].sort()).toEqual([
      "/",
      "/assets/index-new.js",
      "/icon-192.png",
    ]);

    // A page that names no assets, such as an error page, prunes nothing.
    await cache.put("/assets/index-old.js", new Response("old"));
    network.mockResolvedValueOnce(new Response("<p>Hello</p>"));
    await defined(respond(scope, get("/projects", "navigate")));
    expect(stores.get(CACHE)?.has("/assets/index-old.js")).toBe(true);
  });

  it("gives an error page when the Mac is out of reach and nothing is cached", async () => {
    vi.useFakeTimers();
    try {
      let fail: (error: Error) => void = () => undefined;
      const { scope, network } = setup(
        () =>
          new Promise((_, reject) => {
            fail = reject;
          }),
      );
      const late = defined(respond(scope, get("/inbox", "navigate")));
      await vi.advanceTimersByTimeAsync(NAVIGATION_TIMEOUT_MS);
      fail(new TypeError("offline"));
      expect((await late).type).toBe("error");

      network.mockRejectedValueOnce(new TypeError("offline"));
      const failed = await defined(respond(scope, get("/inbox", "navigate")));
      expect(failed.type).toBe("error");
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the manifest and icons fresh, and serves them from the cache offline", async () => {
    const { scope, network } = setup();

    await respond(scope, get("/manifest.webmanifest"));
    network.mockRejectedValue(new TypeError("offline"));
    const offline = await defined(respond(scope, get("/manifest.webmanifest")));

    expect(await offline.text()).toBe("network");
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
  it("shows the daemon's notification with its tag, icon and link, alerting again", async () => {
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
      // A newer notice of the same chat replaces the old one and still alerts.
      renotify: true,
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
