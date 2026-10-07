import { vi } from "vitest";
import { defined } from "./defined.ts";
import type { PushEnv, PushManagerLike, SubscriptionLike } from "../pwa/push.ts";

/** The daemon key the fake API hands out ("BAEC") and the matching bytes. */
export const KEY_BYTES = [4, 1, 2];

export function fakeSubscription(key: number[] = KEY_BYTES, endpoint = "https://push/1") {
  const subscription = {
    endpoint,
    options: { applicationServerKey: new Uint8Array(key).buffer },
    toJSON: () => ({ endpoint, keys: { p256dh: "p", auth: "a" } }),
    unsubscribe: vi.fn(() => Promise.resolve(true)),
  };
  return subscription satisfies SubscriptionLike;
}

interface Options {
  standalone?: boolean;
  permission?: NotificationPermission;
  // What the user answers when asked.
  answer?: NotificationPermission;
  subscription?: SubscriptionLike | null;
  // No Notification API, or no service worker push.
  notification?: boolean;
  push?: boolean;
  registered?: boolean;
}

/** A browser with Notification and PushManager under test control. */
export function fakePushEnv({
  standalone = true,
  permission = "default",
  answer = "granted",
  subscription = null,
  notification = true,
  push = true,
  registered = true,
}: Options = {}) {
  let current = subscription;
  const manager = {
    getSubscription: vi.fn(() => Promise.resolve(current)),
    subscribe: vi.fn((options: Parameters<PushManagerLike["subscribe"]>[0]) => {
      current = fakeSubscription([...options.applicationServerKey], "https://push/new");
      return Promise.resolve(current);
    }),
  } satisfies PushManagerLike;
  const requestPermission = vi.fn(() => {
    perms.permission = answer;
    return Promise.resolve(answer);
  });
  const perms = { permission, requestPermission };
  const env: PushEnv = {
    standalone,
    notification: notification ? perms : undefined,
    serviceWorker: push
      ? {
          getRegistration: () => Promise.resolve(registered ? { pushManager: manager } : undefined),
        }
      : undefined,
  };
  return { env, manager, requestPermission };
}

/**
 * Put a fake Notification, PushManager and service worker into the page, as an installed
 * app has them. Undo with `uninstallBrowserPush`.
 */
export function installBrowserPush(options: Options = {}) {
  // Without push, the worker is still there; only PushManager is missing, as in Safari tabs.
  const fake = fakePushEnv({ ...options, push: true });
  const worker = Object.assign(new EventTarget(), defined(fake.env.serviceWorker));
  vi.stubGlobal("Notification", fake.env.notification);
  vi.stubGlobal("PushManager", options.push === false ? undefined : {});
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: fake.env.standalone && query === "(display-mode: standalone)",
  }));
  Object.defineProperty(window.navigator, "serviceWorker", { value: worker, configurable: true });
  return { ...fake, worker };
}

export function uninstallBrowserPush() {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(window.navigator, "serviceWorker");
}
