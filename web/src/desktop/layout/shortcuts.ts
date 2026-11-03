// The Mac's keyboard shortcuts (NestKit Shortcuts.swift and ShortcutsStore.swift, B81) on
// Linux: Ctrl takes the place of Cmd, and Alt that of Option and of the Mac's Control.
// Each command has its default, or the keys the user chose in Settings, kept per device.

export type ShortcutAction =
  | "settings"
  | "palette"
  | "toggleSidebar"
  | "toggleActivity"
  | "workspace"
  | "board"
  | "artifacts"
  | "newChat"
  | "sendMessage"
  | "closePane"
  | "newTerminal"
  | "newBrowser"
  | "openInVSCode"
  | "previousProject"
  | "nextProject"
  | "project"
  | "pixies";

export interface Shortcut {
  // A lowercased character, a named key ("return", "escape", "tab", "delete", "space",
  // "up", "down", "left", "right"), or "digits" for Project 1 to 9.
  key: string;
  ctrl: boolean;
  shift: boolean;
  alt: boolean;
}

export const DIGITS = "digits";

function keys(key: string, mods: ("shift" | "alt")[] = []): Shortcut {
  return { key, ctrl: true, shift: mods.includes("shift"), alt: mods.includes("alt") };
}

export const SHORTCUT_GROUPS: { title: string; actions: ShortcutAction[] }[] = [
  {
    title: "Window",
    actions: [
      "settings",
      "palette",
      "toggleSidebar",
      "toggleActivity",
      "workspace",
      "board",
      "artifacts",
    ],
  },
  {
    title: "Chats",
    actions: ["newChat", "sendMessage", "closePane", "newTerminal", "newBrowser", "openInVSCode"],
  },
  { title: "Projects", actions: ["previousProject", "nextProject", "project", "pixies"] },
];

/** Every command's title and default keys. */
export const SHORTCUTS: Record<ShortcutAction, { title: string; keys: Shortcut }> = {
  settings: { title: "Settings", keys: keys(",") },
  palette: { title: "Search chats and commands", keys: keys("k") },
  toggleSidebar: { title: "Toggle sidebar", keys: keys("s", ["alt"]) },
  toggleActivity: { title: "Toggle activity panel", keys: keys("a", ["alt"]) },
  workspace: { title: "Workspace", keys: keys("1", ["alt"]) },
  board: { title: "Board", keys: keys("2", ["alt"]) },
  artifacts: { title: "Artifacts", keys: keys("3", ["alt"]) },
  newChat: { title: "New chat", keys: keys("n") },
  sendMessage: { title: "Send message", keys: keys("return") },
  closePane: { title: "Close pane", keys: keys("w") },
  newTerminal: { title: "New terminal", keys: keys("t", ["shift"]) },
  newBrowser: { title: "New browser", keys: keys("b", ["shift"]) },
  openInVSCode: { title: "Open project in VS Code", keys: keys("o", ["shift"]) },
  previousProject: { title: "Previous project", keys: keys("[", ["shift"]) },
  nextProject: { title: "Next project", keys: keys("]", ["shift"]) },
  project: { title: "Project 1 to 9", keys: keys(DIGITS) },
  pixies: { title: "Pixies", keys: keys("0") },
};

const ACTIONS = Object.keys(SHORTCUTS) as ShortcutAction[];

const NAMED: Record<string, string> = {
  return: "Enter",
  escape: "Esc",
  tab: "Tab",
  space: "Space",
  delete: "Backspace",
  up: "Up",
  down: "Down",
  left: "Left",
  right: "Right",
};

function modifierText(shortcut: Shortcut): string {
  return [shortcut.ctrl && "Ctrl", shortcut.alt && "Alt", shortcut.shift && "Shift"]
    .filter(Boolean)
    .join("+");
}

/** "Ctrl+Shift+T", "Ctrl+1 … Ctrl+9". */
export function shortcutText(shortcut: Shortcut): string {
  const mods = modifierText(shortcut);
  const join = (key: string) => (mods === "" ? key : `${mods}+${key}`);
  if (shortcut.key === DIGITS) return `${join("1")} … ${join("9")}`;
  return join(NAMED[shortcut.key] ?? shortcut.key.toUpperCase());
}

/** "ctrl+alt+shift+k", as kept. */
export function storedShortcut(shortcut: Shortcut): string {
  return [shortcut.ctrl && "ctrl", shortcut.alt && "alt", shortcut.shift && "shift", shortcut.key]
    .filter(Boolean)
    .join("+");
}

/** A kept shortcut; null for text that is not one. */
export function parseShortcut(text: string): Shortcut | null {
  const parts = text.split("+");
  const key = parts.pop();
  if (key === undefined || key === "") return null;
  const shortcut: Shortcut = { key, ctrl: false, shift: false, alt: false };
  for (const part of parts) {
    if (part !== "ctrl" && part !== "alt" && part !== "shift") return null;
    shortcut[part] = true;
  }
  return shortcut;
}

function sameModifiers(a: Shortcut, b: Shortcut): boolean {
  return a.ctrl === b.ctrl && a.shift === b.shift && a.alt === b.alt;
}

/** Whether both would answer the same keys. */
export function overlaps(a: Shortcut, b: Shortcut): boolean {
  if (!sameModifiers(a, b)) return false;
  if (a.key === b.key) return true;
  const digit = (key: string) => /^[1-9]$/.test(key);
  return (a.key === DIGITS && digit(b.key)) || (b.key === DIGITS && digit(a.key));
}

const press = (key: string, mods: ("ctrl" | "shift" | "alt")[]): Shortcut => ({
  key,
  ctrl: mods.includes("ctrl"),
  shift: mods.includes("shift"),
  alt: mods.includes("alt"),
});

/**
 * Keys the system, every app or Nest itself uses, never given to a command: quit, the
 * clipboard and undo, a terminal pane's copy and paste, switching windows and input
 * sources, the desktop's terminal and lock keys, and Ctrl+Alt+N, which opens Nest.
 */
export const RESERVED: Shortcut[] = [
  press("q", ["ctrl"]),
  press("c", ["ctrl"]),
  press("v", ["ctrl"]),
  press("x", ["ctrl"]),
  press("a", ["ctrl"]),
  press("z", ["ctrl"]),
  press("z", ["ctrl", "shift"]),
  press("y", ["ctrl"]),
  press("c", ["ctrl", "shift"]),
  press("v", ["ctrl", "shift"]),
  press("tab", ["ctrl"]),
  press("tab", ["alt"]),
  press("`", ["alt"]),
  press("space", ["ctrl"]),
  press("space", ["alt"]),
  press("n", ["ctrl", "alt"]),
  press("t", ["ctrl", "alt"]),
  press("l", ["ctrl", "alt"]),
  press("delete", ["ctrl", "alt"]),
];

/** What recording a new shortcut came to (the Mac's ShortcutChange). */
export type ShortcutChange =
  | { kind: "saved" }
  // Escape alone: the old shortcut stays.
  | { kind: "cancelled" }
  // Another command has it.
  | { kind: "conflict"; other: ShortcutAction }
  | { kind: "reserved" }
  // Without Ctrl or Alt it would be plain typing.
  | { kind: "needsModifier" }
  // Project 1 to 9 is recorded with a digit.
  | { kind: "needsDigit" };

/** What the recorder says when the keys were refused; null when they were not. */
export function changeMessage(change: ShortcutChange, shortcut: Shortcut): string | null {
  switch (change.kind) {
    case "saved":
    case "cancelled":
      return null;
    case "conflict":
      return `${shortcutText(shortcut)} is already ${SHORTCUTS[change.other].title}`;
    case "reserved":
      return `${shortcutText(shortcut)} is used by the system`;
    case "needsModifier":
      return "Use Ctrl or Alt with the key";
    case "needsDigit":
      return "Press the modifiers with a digit, such as Ctrl+1";
  }
}

interface KeyLike {
  key: string;
  code: string;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  metaKey: boolean;
}

const NAMED_KEYS: Record<string, string> = {
  Enter: "return",
  Escape: "escape",
  Tab: "tab",
  Backspace: "delete",
  " ": "space",
  ArrowUp: "up",
  ArrowDown: "down",
  ArrowLeft: "left",
  ArrowRight: "right",
};

// The unshifted character of keys Shift changes, by their physical key.
const UNSHIFTED: Record<string, string> = {
  BracketLeft: "[",
  BracketRight: "]",
  Comma: ",",
  Period: ".",
  Slash: "/",
  Semicolon: ";",
  Quote: "'",
  Backquote: "`",
  Minus: "-",
  Equal: "=",
  Backslash: "\\",
};

/**
 * The key a press names, ignoring modifiers; null for a modifier key alone. Digits and
 * brackets come from the physical key, as do other keys Shift changes while it is held,
 * so Shift (which turns "[" into "{") and the layout do not change them; letters follow
 * the layout.
 */
export function keyName(event: KeyLike): string | null {
  const digit = /^(?:Digit|Numpad)(\d)$/.exec(event.code);
  if (digit !== null) return digit[1] ?? null;
  if (event.code === "BracketLeft" || event.code === "BracketRight") {
    return UNSHIFTED[event.code] ?? null;
  }
  const named = NAMED_KEYS[event.key];
  if (named !== undefined) return named;
  if (event.shiftKey && UNSHIFTED[event.code] !== undefined) return UNSHIFTED[event.code] ?? null;
  return event.key.length === 1 ? event.key.toLowerCase() : null;
}

/** A place to keep the choices: the device's storage, or a test's. */
type KeptStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const PREFIX = "nest.desktop.shortcuts.";

/**
 * The commands' keys: the defaults, or the user's choices kept in `storage` (the Mac's
 * ShortcutsStore). Unreadable kept values are ignored.
 */
export class ShortcutsStore {
  private overrides = new Map<ShortcutAction, Shortcut>();
  private listeners = new Set<() => void>();
  // Changes on every change, for useSyncExternalStore.
  version = 0;
  private readonly storage: KeptStorage | null;

  constructor(storage: KeptStorage | null) {
    this.storage = storage;
    for (const action of ACTIONS) {
      const kept = this.read(PREFIX + action);
      const shortcut = kept === null ? null : parseShortcut(kept);
      if (shortcut !== null) this.overrides.set(action, shortcut);
    }
  }

  shortcut(action: ShortcutAction): Shortcut {
    return this.overrides.get(action) ?? SHORTCUTS[action].keys;
  }

  isDefault(action: ShortcutAction): boolean {
    return !this.overrides.has(action);
  }

  get hasChanges(): boolean {
    return this.overrides.size > 0;
  }

  /** Whether the keys can be the command's shortcut, and why not. */
  check(shortcut: Shortcut, action: ShortcutAction): ShortcutChange {
    if (shortcut.key === "escape" && !shortcut.ctrl && !shortcut.alt && !shortcut.shift) {
      return { kind: "cancelled" };
    }
    if (action === "project" && shortcut.key !== DIGITS) return { kind: "needsDigit" };
    if (!shortcut.ctrl && !shortcut.alt) return { kind: "needsModifier" };
    if (RESERVED.some((reserved) => overlaps(reserved, shortcut))) return { kind: "reserved" };
    const other = ACTIONS.find((a) => a !== action && overlaps(this.shortcut(a), shortcut));
    return other === undefined ? { kind: "saved" } : { kind: "conflict", other };
  }

  /** Gives the command these keys unless they are refused; Escape alone cancels. */
  set(shortcut: Shortcut, action: ShortcutAction): ShortcutChange {
    const change = this.check(shortcut, action);
    if (change.kind !== "saved") return change;
    const fallback = SHORTCUTS[action].keys;
    if (shortcut.key === fallback.key && sameModifiers(shortcut, fallback)) {
      this.overrides.delete(action);
      this.write(PREFIX + action, null);
    } else {
      this.overrides.set(action, shortcut);
      this.write(PREFIX + action, storedShortcut(shortcut));
    }
    this.changed();
    return change;
  }

  /** A key press while recording: Project 1 to 9 takes a digit's modifiers. */
  record(
    event: KeyLike,
    action: ShortcutAction,
  ): { shortcut: Shortcut; change: ShortcutChange } | null {
    if (event.metaKey) return null;
    let key = keyName(event);
    if (key === null) return null;
    if (action === "project" && /^[1-9]$/.test(key)) key = DIGITS;
    const shortcut = { key, ctrl: event.ctrlKey, shift: event.shiftKey, alt: event.altKey };
    return { shortcut, change: this.set(shortcut, action) };
  }

  restoreDefaults(): void {
    for (const action of this.overrides.keys()) this.write(PREFIX + action, null);
    this.overrides.clear();
    this.changed();
  }

  /** The command a key press runs, with the digit for Project 1 to 9; null for others. */
  actionFor(
    event: KeyLike,
  ): { action: "project"; digit: number } | { action: Exclude<ShortcutAction, "project"> } | null {
    if (event.metaKey || (!event.ctrlKey && !event.altKey)) return null;
    const key = keyName(event);
    if (key === null) return null;
    const pressed = { key, ctrl: event.ctrlKey, shift: event.shiftKey, alt: event.altKey };
    for (const action of ACTIONS) {
      const shortcut = this.shortcut(action);
      if (!sameModifiers(shortcut, pressed)) continue;
      if (action === "project") {
        if (/^[1-9]$/.test(key)) return { action, digit: Number(key) };
      } else if (shortcut.key === key) return { action };
    }
    return null;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  private changed() {
    this.version += 1;
    for (const listener of [...this.listeners]) listener();
  }

  private read(key: string): string | null {
    try {
      return this.storage?.getItem(key) ?? null;
    } catch {
      return null;
    }
  }

  private write(key: string, value: string | null) {
    try {
      if (value === null) this.storage?.removeItem(key);
      else this.storage?.setItem(key, value);
    } catch {
      // A blocked storage keeps the choice for this run only.
    }
  }
}

function deviceShortcuts(): ShortcutsStore {
  try {
    return new ShortcutsStore(window.localStorage);
  } catch {
    return new ShortcutsStore(null);
  }
}

/** This device's shortcuts, for the window and Settings. */
export const shortcuts = deviceShortcuts();

/** The command a key press runs with this device's shortcuts. */
export function shortcutFor(event: KeyLike) {
  return shortcuts.actionFor(event);
}

/** A command's keys on this device, as the window shows them. */
export function keysText(action: ShortcutAction): string {
  return shortcutText(shortcuts.shortcut(action));
}
