// The app shell cache: the page, its hashed assets, the manifest and icons. The API is
// never cached, so everything shown comes live from the Mac. Push notifications open the
// item they are about. Assets an older page used leave the cache once a newer page arrives.
//
// The worker is registered as a classic script, so the app must never import this module:
// a module shared by both would be split into a chunk the worker cannot load.

export const CACHE = "harness-shell-v1";
// How long a page may take before the cached shell opens instead.
export const NAVIGATION_TIMEOUT_MS = 4000;
export const SHELL = [
  "/",
  "/manifest.webmanifest",
  "/icon-192.png",
  "/icon-512.png",
  "/apple-touch-icon.png",
];

interface ExtendableEvent {
  waitUntil(promise: Promise<unknown>): void;
}

interface FetchEvent {
  request: Request;
  respondWith(response: Promise<Response>): void;
}

interface PushEvent extends ExtendableEvent {
  data: { json(): unknown } | null;
}

interface NotificationClickEvent extends ExtendableEvent {
  notification: { data: unknown; close(): void };
}

export interface WindowClientLike {
  url: string;
  focus(): Promise<unknown>;
  postMessage(message: NavigateMessage): void;
}

/** Sent to an open app window so it shows the item a notification was about. */
export interface NavigateMessage {
  type: typeof NAVIGATE;
  url: string;
}

// Must match src/pwa/navigate.ts, the app's side.
export const NAVIGATE = "harness:navigate";
export const ICON = "/icon-192.png";

export interface WorkerScope {
  location: { origin: string };
  caches: CacheStorage;
  clients: {
    claim(): Promise<void>;
    matchAll(options: {
      type: "window";
      includeUncontrolled: boolean;
    }): Promise<readonly WindowClientLike[]>;
    openWindow(url: string): Promise<unknown>;
  };
  registration: { showNotification(title: string, options: NotificationOptions): Promise<void> };
  skipWaiting(): Promise<void>;
  fetch(request: Request): Promise<Response>;
  addEventListener(type: "install" | "activate", listener: (event: ExtendableEvent) => void): void;
  addEventListener(type: "fetch", listener: (event: FetchEvent) => void): void;
  addEventListener(type: "push", listener: (event: PushEvent) => void): void;
  addEventListener(
    type: "notificationclick",
    listener: (event: NotificationClickEvent) => void,
  ): void;
}

export function installWorker(scope: WorkerScope): void {
  scope.addEventListener("install", (event) => {
    event.waitUntil(
      scope.caches
        .open(CACHE)
        .then((cache) => cache.addAll(SHELL))
        .then(() => scope.skipWaiting()),
    );
  });
  scope.addEventListener("activate", (event) => {
    event.waitUntil(
      scope.caches
        .keys()
        .then((keys) =>
          Promise.all(keys.filter((k) => k !== CACHE).map((k) => scope.caches.delete(k))),
        )
        .then(() => scope.clients.claim()),
    );
  });
  scope.addEventListener("fetch", (event) => {
    const response = respond(scope, event.request);
    if (response !== null) event.respondWith(response);
  });
  scope.addEventListener("push", (event) => {
    // Every push must show a notification, or iOS ends the subscription.
    event.waitUntil(showPush(scope, event.data));
  });
  scope.addEventListener("notificationclick", (event) => {
    event.notification.close();
    event.waitUntil(openItem(scope, appPath(event.notification.data)));
  });
}

interface PushPayload {
  title: string;
  body: string;
  url: string;
  tag?: string;
}

/** Read the daemon's {title, body, url, tag}; anything unexpected still shows something. */
export function parsePush(data: PushEvent["data"]): PushPayload {
  const raw = readJson(data);
  const fields = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
  const text = (key: string) => (typeof fields[key] === "string" ? fields[key] : undefined);
  const tag = text("tag");
  return {
    title: text("title") ?? "harness",
    body: text("body") ?? "",
    url: appPath({ url: text("url") }),
    ...(tag === undefined ? {} : { tag }),
  };
}

function readJson(data: PushEvent["data"]): unknown {
  try {
    return data?.json() ?? null;
  } catch {
    return null;
  }
}

function showPush(scope: WorkerScope, data: PushEvent["data"]) {
  const { title, body, url, tag } = parsePush(data);
  return scope.registration.showNotification(title, {
    body,
    icon: ICON,
    data: { url },
    ...(tag === undefined ? {} : { tag }),
  });
}

/** Only paths inside the app; anything else opens the inbox. */
function appPath(data: unknown): string {
  const url = typeof data === "object" && data !== null && "url" in data ? data.url : null;
  return typeof url === "string" && url.startsWith("/") && !url.startsWith("//") ? url : "/inbox";
}

/** Focus an open window and send it to the item, or open a new one there. */
export async function openItem(scope: WorkerScope, path: string): Promise<void> {
  const windows = await scope.clients.matchAll({ type: "window", includeUncontrolled: true });
  const open = windows.find((client) => client.url.startsWith(scope.location.origin));
  if (open === undefined) {
    await scope.clients.openWindow(path);
    return;
  }
  await open.focus();
  open.postMessage({ type: NAVIGATE, url: path });
}

/** How the worker answers a request; null leaves it to the network untouched. */
export function respond(scope: WorkerScope, request: Request): Promise<Response> | null {
  if (request.method !== "GET") return null;
  const url = new URL(request.url);
  if (url.origin !== scope.location.origin || url.pathname.startsWith("/api/")) return null;
  if (request.mode === "navigate") return page(scope, request);
  if (url.pathname.startsWith("/assets/")) return cacheFirst(scope, request);
  if (SHELL.includes(url.pathname)) return networkFirst(scope, request, url.pathname);
  return null;
}

/**
 * A page: the network's, unless it fails, answers with a server error (`tailscale serve`
 * with the daemon down) or takes too long (a sleeping Mac); then the cached shell, when
 * there is one. A page that arrives late still refreshes the cache.
 */
async function page(scope: WorkerScope, request: Request): Promise<Response> {
  const cache = await scope.caches.open(CACHE);
  const network = scope.fetch(request).then(async (response) => {
    if (response.ok) await keepPage(cache, response);
    return response;
  });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<"late">((resolve) => {
    timer = setTimeout(() => {
      resolve("late");
    }, NAVIGATION_TIMEOUT_MS);
  });
  const answer = await Promise.race([network.catch(() => null), late]);
  clearTimeout(timer);
  if (answer instanceof Response && answer.status < 500) return answer;
  const shell = await cache.match("/");
  if (shell !== undefined) return shell;
  if (answer === "late") return network.catch(() => Response.error());
  return answer ?? Response.error();
}

/** Caches the page and drops the hashed assets it no longer names. */
async function keepPage(cache: Cache, response: Response): Promise<void> {
  const html = await response.clone().text();
  await cache.put("/", response.clone());
  const used = new Set(html.match(/\/assets\/[^"'\s)]+/g));
  // A page naming no assets (an error page, say) is no guide to what is stale.
  if (used.size === 0) return;
  for (const request of await cache.keys()) {
    const path = new URL(request.url).pathname;
    if (path.startsWith("/assets/") && !used.has(path)) await cache.delete(request);
  }
}

async function networkFirst(scope: WorkerScope, request: Request, key: string) {
  const cache = await scope.caches.open(CACHE);
  try {
    const response = await scope.fetch(request);
    if (response.ok) await cache.put(key, response.clone());
    return response;
  } catch {
    return (await cache.match(key)) ?? Response.error();
  }
}

async function cacheFirst(scope: WorkerScope, request: Request) {
  const cache = await scope.caches.open(CACHE);
  const cached = await cache.match(request);
  if (cached !== undefined) return cached;
  const response = await scope.fetch(request);
  if (response.ok) await cache.put(request, response.clone());
  return response;
}
