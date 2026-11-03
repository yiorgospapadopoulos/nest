// Ported from NestKitTests: the composer's keys (ComposerKeys) and what a rewind can do
// (RewindTests), as the Mac decides them.
import { describe, expect, it } from "vitest";
import type { RewindPreview } from "../../api/types.ts";
import { EscapeRepeat, keyAction } from "./composerKeys.ts";
import { choices, firstChoice, reason, summary } from "./rewindFlow.ts";

describe("the composer's keys", () => {
  it("gives the arrows, Tab, Return and Esc to an open suggestion list", () => {
    expect(keyAction("down", true, false, false, false)).toEqual({ kind: "move", delta: 1 });
    expect(keyAction("up", true, true, false, false)).toEqual({ kind: "move", delta: -1 });
    expect(keyAction("tab", true, false, false, false).kind).toBe("insert");
    expect(keyAction("enter", true, false, false, false).kind).toBe("insert");
    expect(keyAction("escape", true, false, true, false).kind).toBe("close");
    expect(keyAction("shiftEnter", true, false, false, false).kind).toBe("ignore");
  });

  it("sends on Return, interrupts on Esc while working, rewinds on Esc Esc, recalls on Up", () => {
    expect(keyAction("enter", false, false, false, false).kind).toBe("send");
    expect(keyAction("shiftEnter", false, false, false, false).kind).toBe("ignore");
    expect(keyAction("escape", false, false, true, true).kind).toBe("interrupt");
    expect(keyAction("escape", false, false, false, true).kind).toBe("rewind");
    expect(keyAction("escape", false, false, false, false).kind).toBe("ignore");
    expect(keyAction("up", false, true, false, false).kind).toBe("recall");
    expect(keyAction("up", false, false, false, false).kind).toBe("ignore");
  });

  it("counts two Esc presses within 0.6 s as Esc Esc, once", () => {
    const escapes = new EscapeRepeat();
    expect(escapes.press(0)).toBe(false);
    expect(escapes.press(500)).toBe(true);
    expect(escapes.press(700)).toBe(false);
    expect(escapes.press(1400)).toBe(false);
  });
});

const preview = (over: Partial<RewindPreview> = {}): RewindPreview => ({
  can_rewind: true,
  files_changed: ["a.ts", "b.ts"],
  insertions: 12,
  deletions: 4,
  error: null,
  ...over,
});

describe("rewinding to before a message", () => {
  it("offers Edit only the conversation and both; Rewind all three", () => {
    expect(choices("edit")).toEqual(["conversation", "both"]);
    expect(choices("rewind")).toEqual(["conversation", "code", "both"]);
  });

  it("says why a part cannot be restored, and both needs both", () => {
    const none = preview({ files_changed: 0 });
    expect(reason("code", none, preview())).toBe("Nothing to restore");
    expect(reason("both", none, preview())).toBe("Nothing to restore");
    expect(reason("conversation", none, preview())).toBeNull();
    const refused = preview({ can_rewind: false, error: "No checkpoint" });
    expect(reason("conversation", preview(), refused)).toBe("No checkpoint");
    expect(reason("code", null, preview())).not.toBeNull();
  });

  it("starts on both parts for Rewind, the conversation for Edit, the first that can be done", () => {
    expect(firstChoice("rewind", preview(), preview())).toBe("both");
    expect(firstChoice("rewind", preview({ files_changed: 0 }), preview())).toBe("conversation");
    expect(firstChoice("rewind", preview(), preview({ can_rewind: false }))).toBe("code");
    expect(firstChoice("edit", preview(), preview())).toBe("conversation");
    expect(summary(preview())).toBe("2 files change: +12 -4");
    expect(summary(preview({ files_changed: 0 }))).toBe("No files changed since this message.");
  });
});
