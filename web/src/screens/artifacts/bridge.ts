import { useEffect, useRef, type RefObject } from "react";
import { safeName } from "./files.ts";

/**
 * The host side of the page bridge (B88): an artifact page's shim posts requests to the app,
 * which checks each one and answers it. The checks are the same on the Mac (NestKit
 * ArtifactBridge). A new method is one entry in METHODS plus its handler.
 */

export type ErrorCode =
  | "unknown_method"
  | "bad_request"
  | "too_large"
  | "rate_limited"
  | "busy"
  | "declined"
  | "conflict"
  | "quota"
  | "budget"
  | "disabled"
  | "unavailable";

export type Reply =
  | { nest: 1; id: string; ok: true; result: unknown }
  | { nest: 1; id: string; ok: false; error: { code: ErrorCode; message: string } };

/** A refusal a handler gives, answered to the page with its code. */
export class BridgeError extends Error {
  readonly code: ErrorCode;
  constructor(code: ErrorCode, message: string) {
    super(message);
    this.code = code;
  }
}

export const MAX_REQUEST_BYTES = 64 * 1024;
// A saved document is at most the 1 MiB an artifact holds, and the request around it.
export const MAX_SAVE_BYTES = 1024 * 1024 + 1024;
// What a page stores (2 MiB in all) and the request around it.
export const MAX_STORAGE_BYTES = 2 * 1024 * 1024 + 4096;
// A file a page offers to save.
export const MAX_FILE_BYTES = 24 * 1024 * 1024;
// A question a page asks Claude: the prompt, a system text and the request around them.
export const MAX_ASK_BYTES = 16 * 1024;
const MAX_PROMPT = 8000;
const MAX_SYSTEM = 4000;
const MAX_KEY = 256;
const BASE64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;
/** The host event that asks the page to print itself (iPhone; the Mac prints the view). */
export const PRINT = { nest: 1, event: "print" } as const;
const MAX_ID = 64;
const MAX_LINK = 2048;
// A link longer than this shows its host on a line of its own first.
const LONG_LINK = 60;

type Params = Record<string, unknown>;

/** The methods a page may call, each reading its params into the handler's arguments. */
const METHODS = {
  openLink(params: Params): { url: string } {
    const url = checkLink(params.url);
    if (url === null) {
      throw new BridgeError("bad_request", "openLink needs an absolute http, https or mailto URL.");
    }
    return { url };
  },
  saveDocument(params: Params): { content: string; base_version: number } {
    const { content, base_version } = params;
    if (
      typeof content !== "string" ||
      typeof base_version !== "number" ||
      !Number.isInteger(base_version) ||
      base_version < 1
    ) {
      throw new BridgeError(
        "bad_request",
        "saveDocument needs the content as text and the base_version it was edited from.",
      );
    }
    return { content, base_version };
  },
  storageWrite(params: Params): StorageWrite {
    const { set = {}, remove = [] } = params;
    const refuse = () =>
      new BridgeError(
        "bad_request",
        "storageWrite needs set (keys of 1 to 256 characters to text) and remove (keys).",
      );
    if (!isObject(set) || !Array.isArray(remove)) throw refuse();
    const entries = Object.entries(set);
    const keys = [...entries.map(([key]) => key), ...(remove as unknown[])];
    if (entries.some(([, value]) => typeof value !== "string") || !keys.every(isKey)) {
      throw refuse();
    }
    return { set: set as Record<string, string>, remove: remove as string[] };
  },
  storageClear(): Record<string, never> {
    return {};
  },
  saveFile(params: Params): FileToSave {
    const { content, encoding = "utf8" } = params;
    const name = typeof params.name === "string" ? safeName(params.name) : "";
    if (name === "" || typeof content !== "string") {
      throw new BridgeError("bad_request", "saveFile needs a name and the content as text.");
    }
    if (encoding !== "utf8" && (encoding !== "base64" || !BASE64.test(content))) {
      throw new BridgeError("bad_request", "saveFile takes utf8 text or valid base64.");
    }
    return { name, content, encoding };
  },
  usage(): Record<string, never> {
    return {};
  },
  ask(params: Params): Question {
    const { prompt, system } = params;
    if (
      typeof prompt !== "string" ||
      prompt.length < 1 ||
      prompt.length > MAX_PROMPT ||
      (system !== undefined && (typeof system !== "string" || system.length > MAX_SYSTEM))
    ) {
      throw new BridgeError(
        "bad_request",
        "ask needs a prompt of 1 to 8,000 characters and at most 4,000 of system text.",
      );
    }
    return system === undefined ? { prompt } : { prompt, system };
  },
};

export interface Question {
  prompt: string;
  system?: string;
}

export interface StorageWrite {
  set: Record<string, string>;
  remove: string[];
}

export interface FileToSave {
  name: string;
  content: string;
  encoding: "utf8" | "base64";
}

function isKey(key: unknown): boolean {
  return typeof key === "string" && key.length >= 1 && key.length <= MAX_KEY;
}

// Methods allowed more than MAX_REQUEST_BYTES.
const LIMITS: Partial<Record<Method, number>> = {
  saveDocument: MAX_SAVE_BYTES,
  storageWrite: MAX_STORAGE_BYTES,
  saveFile: MAX_FILE_BYTES,
  ask: MAX_ASK_BYTES,
};

export type Method = keyof typeof METHODS;
type Args<M extends Method> = ReturnType<(typeof METHODS)[M]>;
export type Handlers = { [M in Method]: (args: Args<M>) => Promise<unknown> };
export type Call = { [M in Method]: { id: string; method: M; args: Args<M> } }[Method];

/** A change to an artifact's stored data, as the daemon reports it (`artifact.storage`). */
export interface StorageChange extends StorageWrite {
  clear: boolean;
}

export type StorageEvent =
  | { nest: 1; event: "storage"; key: string; value: string | null }
  | { nest: 1; event: "storage"; clear: true };

/** The host events that bring an open page in step with a change made elsewhere. */
export function storageEvents(change: StorageChange): StorageEvent[] {
  const events: StorageEvent[] = change.clear ? [{ nest: 1, event: "storage", clear: true }] : [];
  for (const [key, value] of Object.entries(change.set)) {
    events.push({ nest: 1, event: "storage", key, value });
  }
  for (const key of change.remove) events.push({ nest: 1, event: "storage", key, value: null });
  return events;
}

export function succeed(id: string, result: unknown): Reply {
  return { nest: 1, id, ok: true, result };
}

export function fail(id: string, code: ErrorCode, message: string): Reply {
  return { nest: 1, id, ok: false, error: { code, message } };
}

/**
 * A sliding window: true while fewer than `limit` requests were allowed in the last `span`
 * milliseconds, counting this one. Refused requests do not count.
 */
export function rateWindow(now: () => number, limit = 30, span = 10_000): () => boolean {
  let times: number[] = [];
  return () => {
    const time = now();
    times = times.filter((at) => at > time - span);
    if (times.length >= limit) return false;
    times.push(time);
    return true;
  };
}

function isObject(value: unknown): value is Params {
  if (typeof value !== "object" || value === null) return false;
  const proto = Object.getPrototypeOf(value) as unknown;
  return proto === Object.prototype || proto === null;
}

function bytes(value: unknown): number | null {
  try {
    return new TextEncoder().encode(JSON.stringify(value)).length;
  } catch {
    return null;
  }
}

/**
 * A message from the page as a call to make, or the reply that refuses it, or null when it
 * has no usable id and so cannot be answered. `allow` is the page's rate window.
 */
export function admit(
  data: unknown,
  allow: () => boolean,
): { call: Call } | { reply: Reply } | null {
  if (!isObject(data)) return null;
  const id = data.id;
  if (typeof id !== "string" || id.length === 0 || id.length > MAX_ID) return null;
  const refuse = (code: ErrorCode, message: string) => ({ reply: fail(id, code, message) });
  if (!allow()) return refuse("rate_limited", "Too many requests; wait a few seconds.");
  const { method, params } = data;
  if (data.nest !== 1 || typeof method !== "string" || !isObject(params)) {
    return refuse("bad_request", "A request needs nest: 1, an id, a method and params.");
  }
  const size = bytes(data);
  if (size === null) return refuse("bad_request", "The request cannot be read as JSON.");
  const known = Object.hasOwn(METHODS, method);
  const limit = (known ? LIMITS[method as Method] : undefined) ?? MAX_REQUEST_BYTES;
  if (size > limit) {
    return refuse("too_large", `The request is over ${String(limit / 1024)} KiB.`);
  }
  if (!known) return refuse("unknown_method", `Nest has no method ${method}.`);
  const name = method as Method;
  try {
    // A method and its own args: TypeScript cannot pair them through the lookup.
    return { call: { id, method: name, args: METHODS[name](params) } as Call };
  } catch (error) {
    const refused = error as BridgeError;
    return refuse(refused.code, refused.message);
  }
}

/**
 * The address a link opens, or null unless it is an absolute http, https or mailto URL of at
 * most 2,048 characters: the Mac's SafeLink rule. Script, data, file and app schemes never
 * open, nor do relative links.
 */
export function checkLink(url: unknown): string | null {
  if (typeof url !== "string" || url.length > MAX_LINK) return null;
  if (!/^(https?:\/\/|mailto:)/i.test(url)) return null;
  try {
    return new URL(url).href;
  } catch {
    return null;
  }
}

/** A link as the confirm sheet shows it: in full, its host first when it is long. */
export function linkMessage(url: string): string {
  const host = new URL(url).host;
  return url.length > LONG_LINK && host !== "" ? `${host}\n${url}` : url;
}

/**
 * Answers the page in the frame for as long as the caller is mounted: one window message
 * listener, which takes messages only from this frame's window. A new frame needs a new
 * mount (a key), which also starts a fresh rate window. Replies after unmount are dropped.
 */
export function useArtifactBridge(
  frameRef: RefObject<HTMLIFrameElement | null>,
  handlers: Handlers,
  now: () => number = Date.now,
): void {
  const latest = useRef(handlers);
  useEffect(() => {
    latest.current = handlers;
  });
  useEffect(() => {
    const allow = rateWindow(now);
    let live = true;
    const onMessage = (event: MessageEvent) => {
      const frame = frameRef.current?.contentWindow;
      if (frame == null || event.source !== frame) return;
      const admitted = admit(event.data, allow);
      if (admitted === null) return;
      const answer = (reply: Reply) => {
        if (live) frame.postMessage(reply, "*");
      };
      if ("reply" in admitted) {
        answer(admitted.reply);
        return;
      }
      const { id, method, args } = admitted.call;
      const handler = latest.current[method] as (given: typeof args) => Promise<unknown>;
      new Promise((resolve) => {
        resolve(handler(args));
      }).then(
        (result) => {
          answer(succeed(id, result));
        },
        (error: unknown) => {
          answer(
            error instanceof BridgeError
              ? fail(id, error.code, error.message)
              : fail(id, "unavailable", "Nest could not do that."),
          );
        },
      );
    };
    window.addEventListener("message", onMessage);
    return () => {
      live = false;
      window.removeEventListener("message", onMessage);
    };
  }, [frameRef, now]);
}
