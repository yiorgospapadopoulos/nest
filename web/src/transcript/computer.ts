// Computer use (B150) in the transcript: the names of what a chat uses, what it holds now,
// and its tool calls as plain lines such as "Pressed in TextEdit".
import { COMPUTER_STATE } from "../api/events.ts";
import { list, obj, str } from "../api/payloads.ts";
import type { JsonObject, NestEvent } from "../api/types.ts";

export interface HeldTarget {
  key: string;
  name: string;
}

const PREFIX = "mcp__nest__computer_";

export function isComputerTool(name: string): boolean {
  return name.startsWith(PREFIX);
}

const KIND_NAMES: Record<string, string> = {
  ios: "iOS Simulator",
  android: "Android Emulator",
  browser: "Shared browser",
};

/**
 * A target's name: the one the daemon gave it, else from its key, such as TextEdit for
 * `mac:com.apple.TextEdit`.
 */
export function targetName(key: string, names?: ReadonlyMap<string, string>): string {
  const known = names?.get(key);
  if (known !== undefined) return known;
  const [kind = "", rest = ""] = key.split(/:(.*)/);
  if (kind === "mac" && rest !== "") return rest.split(".").at(-1) ?? rest;
  return KIND_NAMES[kind] ?? key;
}

function targetsOf(event: NestEvent): HeldTarget[] {
  return list(event.payload.targets).flatMap((value) => {
    const target = obj(value);
    const key = str(target.key);
    return key === null ? [] : [{ key, name: str(target.name) ?? targetName(key) }];
  });
}

/** Every target name the chat's `computer.state` events gave, by key. */
export function computerNames(events: readonly NestEvent[]): Map<string, string> {
  const names = new Map<string, string>();
  for (const event of events) {
    if (event.type !== COMPUTER_STATE) continue;
    for (const target of targetsOf(event)) names.set(target.key, target.name);
  }
  return names;
}

const NOTHING: readonly HeldTarget[] = [];

/** What the chat holds now: its latest `computer.state`, nothing before one. */
export function heldTargets(events: readonly NestEvent[] | undefined): readonly HeldTarget[] {
  const last = events?.findLast((event) => event.type === COMPUTER_STATE);
  return last === undefined ? NOTHING : targetsOf(last);
}

function keysOf(input: JsonObject): string {
  const modifiers = list(input.modifiers).flatMap((m) => {
    const text = str(m);
    return text === null ? [] : [text.charAt(0).toUpperCase() + text.slice(1)];
  });
  const key = str(input.key) ?? "";
  return [...modifiers, key.charAt(0).toUpperCase() + key.slice(1)].join("-");
}

/** What an act did, as a verb and the rest of its line. */
function actLine(input: JsonObject, where: string): { name: string; arg: string } {
  switch (str(input.action)) {
    case "press":
      return { name: "Pressed", arg: where };
    case "click":
      return { name: "Clicked", arg: where };
    case "type":
    case "set_value":
      return { name: "Typed", arg: where };
    case "key":
      return { name: "Pressed", arg: `${keysOf(input)} ${where}` };
    case "menu": {
      const path = list(input.menu).flatMap((m) => str(m) ?? []);
      return { name: "Chose", arg: `${path.join(" > ")} ${where}` };
    }
    case "scroll":
      return { name: "Scrolled", arg: where };
    case "focus":
      return { name: "Focused", arg: where };
    case "navigate":
      return { name: "Opened", arg: `${str(input.url) ?? "a link"} ${where}` };
    default:
      return { name: "Used", arg: where };
  }
}

/** A computer use call's line, by the target's name; null for any other tool. */
export function computerCall(
  tool: string,
  input: JsonObject,
  names: ReadonlyMap<string, string>,
): { name: string; arg: string } | null {
  if (!isComputerTool(tool)) return null;
  const target = targetName(str(input.target) ?? "", names);
  switch (tool.slice(PREFIX.length)) {
    case "targets":
      return { name: "Listed", arg: "what it can use" };
    case "open":
      return { name: "Opened", arg: target };
    case "view":
      return { name: "Looked at", arg: target };
    case "act":
      return actLine(input, `in ${target}`);
    case "release":
      return { name: "Let go of", arg: target };
    default:
      return { name: "Used", arg: target };
  }
}

const NAMED = /^(Pressed|Set|Typed|Chose|Clicked|Focused|Scrolled) (.*"[^"]+".*?)\.?$/;

/**
 * An act's own first line once its element has a name, such as `Pressed "Send" in Mail.`,
 * which says more than its input can (the input only has the element's id).
 */
export function namedAction(content: string): { name: string; arg: string } | null {
  const match = NAMED.exec(content.split("\n", 1)[0] ?? "");
  return match === null ? null : { name: match[1] ?? "", arg: match[2] ?? "" };
}
