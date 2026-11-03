// The Mac's shortcuts with Ctrl for Cmd: the right command runs, plain typing never does.
import { describe, expect, it } from "vitest";
import { clampSidebar, SIDEBAR_MAXIMUM, SIDEBAR_MINIMUM, storedSidebar } from "./sidebar.ts";
import { memoryStorage } from "../../test/render.tsx";
import {
  changeMessage,
  parseShortcut,
  SHORTCUTS,
  shortcutFor,
  ShortcutsStore,
  shortcutText,
  type Shortcut,
} from "./shortcuts.ts";

function press(key: string, code: string, mods: { shift?: boolean; alt?: boolean } = {}) {
  return {
    key,
    code,
    ctrlKey: true,
    shiftKey: mods.shift ?? false,
    altKey: mods.alt ?? false,
    metaKey: false,
  };
}

describe("keyboard shortcuts", () => {
  it("answer the Mac's commands with Ctrl", () => {
    expect(shortcutFor(press("k", "KeyK"))).toEqual({ action: "palette" });
    expect(shortcutFor(press("N", "KeyN"))).toEqual({ action: "newChat" });
    expect(shortcutFor(press("T", "KeyT", { shift: true }))).toEqual({ action: "newTerminal" });
    expect(shortcutFor(press(",", "Comma"))).toEqual({ action: "settings" });
    expect(shortcutFor(press("s", "KeyS", { alt: true }))).toEqual({ action: "toggleSidebar" });
    expect(shortcutFor(press("2", "Digit2", { alt: true }))).toEqual({ action: "board" });
  });

  it("read digits and brackets from the key, whatever Shift makes of them", () => {
    expect(shortcutFor(press("3", "Digit3"))).toEqual({ action: "project", digit: 3 });
    expect(shortcutFor(press("0", "Digit0"))).toEqual({ action: "pixies" });
    expect(shortcutFor(press("{", "BracketLeft", { shift: true }))).toEqual({
      action: "previousProject",
    });
    expect(shortcutFor(press("}", "BracketRight", { shift: true }))).toEqual({
      action: "nextProject",
    });
  });

  it("leave typing, other modifiers and unknown keys alone", () => {
    expect(shortcutFor({ ...press("k", "KeyK"), ctrlKey: false })).toBeNull();
    expect(shortcutFor({ ...press("k", "KeyK"), metaKey: true })).toBeNull();
    expect(shortcutFor(press("c", "KeyC"))).toBeNull();
    // Ctrl Alt N is the system-wide shortcut that opens Nest, not a window command.
    expect(shortcutFor(press("n", "KeyN", { alt: true }))).toBeNull();
    expect(shortcutFor(press("Shift", "ShiftLeft", { shift: true }))).toBeNull();
  });

  it("show as Linux writes them", () => {
    expect(shortcutText(SHORTCUTS.newTerminal.keys)).toBe("Ctrl+Shift+T");
    expect(shortcutText(SHORTCUTS.project.keys)).toBe("Ctrl+1 … Ctrl+9");
    expect(shortcutText(SHORTCUTS.sendMessage.keys)).toBe("Ctrl+Enter");
  });
});

// Ported from NestKitTests' ShortcutTests and ShortcutsStoreTests (B81).
describe("changing a shortcut", () => {
  const kept = () => memoryStorage();
  const ctrl = (key: string, mods: ("shift" | "alt")[] = []): Shortcut => ({
    key,
    ctrl: true,
    shift: mods.includes("shift"),
    alt: mods.includes("alt"),
  });

  it("keeps the defaults until changed, and the change between starts, per device", () => {
    const storage = kept();
    const store = new ShortcutsStore(storage);
    expect(store.shortcut("newChat")).toEqual(ctrl("n"));
    expect(store.hasChanges).toBe(false);
    expect(store.set(ctrl("j", ["shift"]), "newChat")).toEqual({ kind: "saved" });
    expect(storage.getItem("nest.desktop.shortcuts.newChat")).toBe("ctrl+shift+j");
    expect(new ShortcutsStore(storage).shortcut("newChat")).toEqual(ctrl("j", ["shift"]));
    expect(new ShortcutsStore(storage).actionFor(press("J", "KeyJ", { shift: true }))).toEqual({
      action: "newChat",
    });
    expect(new ShortcutsStore(storage).actionFor(press("n", "KeyN"))).toBeNull();
    // Back to the default forgets the choice.
    expect(store.set(ctrl("n"), "newChat")).toEqual({ kind: "saved" });
    expect(store.isDefault("newChat")).toBe(true);
    expect(storage.getItem("nest.desktop.shortcuts.newChat")).toBeNull();
  });

  it("ignores kept values that are not shortcuts", () => {
    const storage = kept();
    storage.setItem("nest.desktop.shortcuts.palette", "hyper+k");
    expect(new ShortcutsStore(storage).shortcut("palette")).toEqual(ctrl("k"));
    expect(parseShortcut("ctrl++")).toBeNull();
    expect(parseShortcut("")).toBeNull();
  });

  it("refuses another command's keys, the system's, plain typing and Project without a digit", () => {
    const store = new ShortcutsStore(kept());
    expect(store.set({ ...ctrl("escape"), ctrl: false }, "newChat")).toEqual({
      kind: "cancelled",
    });
    expect(store.set(ctrl("k"), "newChat")).toEqual({ kind: "conflict", other: "palette" });
    expect(store.set(ctrl("q"), "newChat")).toEqual({ kind: "reserved" });
    expect(store.set(ctrl("v", ["shift"]), "newChat")).toEqual({ kind: "reserved" });
    expect(store.set(ctrl("n", ["alt"]), "palette")).toEqual({ kind: "reserved" });
    expect(store.set({ ...ctrl("j", ["shift"]), ctrl: false }, "newChat")).toEqual({
      kind: "needsModifier",
    });
    expect(store.set(ctrl("j"), "project")).toEqual({ kind: "needsDigit" });
    expect(store.set(ctrl("1", ["alt"]), "newChat")).toEqual({
      kind: "conflict",
      other: "workspace",
    });
    expect(store.set(ctrl("4"), "newChat")).toEqual({ kind: "conflict", other: "project" });
    expect(store.isDefault("newChat")).toBe(true);
    // Alt alone is enough, as Option is on the Mac.
    expect(store.set({ ...ctrl("j", ["alt"]), ctrl: false }, "newChat")).toEqual({
      kind: "saved",
    });
  });

  it("says why keys were refused", () => {
    const keys = ctrl("k");
    expect(changeMessage({ kind: "conflict", other: "palette" }, keys)).toBe(
      "Ctrl+K is already Search chats and commands",
    );
    expect(changeMessage({ kind: "reserved" }, keys)).toBe("Ctrl+K is used by the system");
    expect(changeMessage({ kind: "needsModifier" }, keys)).toBe("Use Ctrl or Alt with the key");
    expect(changeMessage({ kind: "saved" }, keys)).toBeNull();
  });

  it("records a press, Project 1 to 9 from a digit, and nothing for a modifier alone", () => {
    const store = new ShortcutsStore(kept());
    const saved = store.record(press("j", "KeyJ", { alt: true }), "newTerminal");
    expect(saved).toEqual({ shortcut: ctrl("j", ["alt"]), change: { kind: "saved" } });
    const digits = store.record(press("1", "Digit1", { alt: true }), "project");
    // Ctrl Alt 1 to 3 are Workspace, Board and Artifacts.
    expect(digits?.change).toEqual({ kind: "conflict", other: "workspace" });
    expect(store.record(press("!", "Digit1", { shift: true }), "project")?.change).toEqual({
      kind: "saved",
    });
    expect(shortcutText(store.shortcut("project"))).toBe("Ctrl+Shift+1 … Ctrl+Shift+9");
    expect(store.actionFor(press("%", "Digit5", { shift: true }))).toEqual({
      action: "project",
      digit: 5,
    });
    expect(store.record(press("Shift", "ShiftLeft", { shift: true }), "newChat")).toBeNull();
    const shifted = store.record(press("<", "Comma", { shift: true }), "settings");
    expect(shifted?.shortcut).toEqual(ctrl(",", ["shift"]));
  });

  it("restores every default", () => {
    const storage = kept();
    const store = new ShortcutsStore(storage);
    store.set(ctrl("j", ["shift"]), "newChat");
    store.set(ctrl("y", ["shift"]), "palette");
    expect(store.hasChanges).toBe(true);
    store.restoreDefaults();
    expect(store.hasChanges).toBe(false);
    expect(storage.getItem("nest.desktop.shortcuts.palette")).toBeNull();
    expect(new ShortcutsStore(storage).shortcut("palette")).toEqual(ctrl("k"));
  });
});

describe("sidebar width", () => {
  it("stays within its bounds and leaves the workspace room for a pane", () => {
    expect(clampSidebar(300, 2000)).toBe(300);
    expect(clampSidebar(120, 2000)).toBe(SIDEBAR_MINIMUM);
    expect(clampSidebar(900, 2000)).toBe(SIDEBAR_MAXIMUM);
    expect(clampSidebar(420, 650)).toBe(650 - 280);
    expect(clampSidebar(300, 300)).toBe(SIDEBAR_MINIMUM);
  });

  it("reads a saved width back within bounds, the standard one when unreadable", () => {
    expect(storedSidebar(null)).toBe(236);
    expect(storedSidebar("wide")).toBe(236);
    expect(storedSidebar("")).toBe(236);
    expect(storedSidebar("312.5")).toBe(312.5);
    expect(storedSidebar("5000")).toBe(SIDEBAR_MAXIMUM);
  });
});
