// Web push from the installed app. On iOS, push exists only in a Home Screen app, and the
// permission prompt must come straight from a tap, so `enablePush` asks before anything else.

import type { PushSubscriptionBody } from "../api/types.ts";

export interface SubscriptionLike {
  endpoint: string;
  options: { applicationServerKey: ArrayBuffer | null };
  toJSON(): PushSubscriptionJSON;
  unsubscribe(): Promise<boolean>;
}

export interface PushManagerLike {
  getSubscription(): Promise<SubscriptionLike | null>;
  subscribe(options: {
    userVisibleOnly: true;
    applicationServerKey: Uint8Array<ArrayBuffer>;
  }): Promise<SubscriptionLike>;
}

export interface PushEnv {
  // Opened from the Home Screen rather than in a browser tab.
  standalone: boolean;
  notification:
    | {
        permission: NotificationPermission;
        requestPermission(): Promise<NotificationPermission>;
      }
    | undefined;
  serviceWorker:
    { getRegistration(): Promise<{ pushManager: PushManagerLike } | undefined> } | undefined;
}

export type PushStatus = "install" | "unsupported" | "denied" | "off" | "on";

export interface PushServer {
  vapidKey(): Promise<{ public_key: string }>;
  subscribePush(subscription: PushSubscriptionBody): Promise<null>;
  unsubscribePush(endpoint: string): Promise<null>;
}

interface BrowserWindow {
  matchMedia?: (query: string) => { matches: boolean };
  Notification?: PushEnv["notification"];
  PushManager?: unknown;
  navigator: { standalone?: boolean; serviceWorker?: PushEnv["serviceWorker"] };
}

export function browserPushEnv(win: BrowserWindow): PushEnv {
  const standalone =
    win.matchMedia?.("(display-mode: standalone)").matches === true ||
    win.navigator.standalone === true;
  const pushable = win.PushManager !== undefined && win.navigator.serviceWorker !== undefined;
  return {
    standalone,
    notification: win.Notification,
    serviceWorker: pushable ? win.navigator.serviceWorker : undefined,
  };
}

async function pushManager(env: PushEnv): Promise<PushManagerLike | undefined> {
  return (await env.serviceWorker?.getRegistration())?.pushManager;
}

export async function pushStatus(env: PushEnv): Promise<PushStatus> {
  if (env.notification === undefined || env.serviceWorker === undefined) {
    return env.standalone ? "unsupported" : "install";
  }
  if (env.notification.permission === "denied") return "denied";
  if (env.notification.permission !== "granted") return "off";
  // Right after the first launch the worker may still be registering: not subscribed yet.
  const subscription = await (await pushManager(env))?.getSubscription();
  return subscription == null ? "off" : "on";
}

/** Ask for permission, subscribe with the daemon's key and register with the daemon. */
export async function enablePush(env: PushEnv, server: PushServer): Promise<PushStatus> {
  if (env.notification === undefined) return pushStatus(env);
  const permission = await env.notification.requestPermission();
  if (permission !== "granted") return permission === "denied" ? "denied" : "off";
  const manager = await pushManager(env);
  if (manager === undefined) {
    throw new Error("harness is still setting up on this device. Reopen it and try again.");
  }
  const key = base64UrlToBytes((await server.vapidKey()).public_key);
  let subscription = await manager.getSubscription();
  if (subscription !== null && !sameKey(subscription.options.applicationServerKey, key)) {
    // Made for another daemon key; the push service would refuse every message.
    await subscription.unsubscribe();
    subscription = null;
  }
  subscription ??= await manager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  await server.subscribePush(subscriptionBody(subscription));
  return "on";
}

export async function disablePush(env: PushEnv, server: PushServer): Promise<PushStatus> {
  const subscription = await (await pushManager(env))?.getSubscription();
  if (subscription != null) {
    await server.unsubscribePush(subscription.endpoint);
    await subscription.unsubscribe();
  }
  return "off";
}

export function subscriptionBody(subscription: SubscriptionLike): PushSubscriptionBody {
  const { endpoint, keys } = subscription.toJSON();
  const p256dh = keys?.p256dh;
  const auth = keys?.auth;
  if (endpoint === undefined || p256dh === undefined || auth === undefined) {
    throw new Error("The browser gave no push keys");
  }
  return { endpoint, keys: { p256dh, auth } };
}

export function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(base64 + "=".repeat((4 - (base64.length % 4)) % 4));
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function sameKey(current: ArrayBuffer | null, key: Uint8Array): boolean {
  if (current === null) return false;
  const bytes = new Uint8Array(current);
  return bytes.length === key.length && bytes.every((byte, i) => byte === key[i]);
}
