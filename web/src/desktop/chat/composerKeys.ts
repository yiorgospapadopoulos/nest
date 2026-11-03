// The composer's keys, ported from NestKit's ComposerKeys.swift: an open suggestion list
// takes the arrows, Tab, Return and Esc; otherwise Return sends (Shift-Return adds a
// line), Esc interrupts a running turn, Esc Esc rewinds, and Up in an empty field recalls
// the last message.

export type ComposerKey = "enter" | "shiftEnter" | "up" | "down" | "tab" | "escape";

export type KeyAction =
  | { kind: "move"; delta: 1 | -1 }
  | { kind: "insert" | "close" | "send" | "interrupt" | "recall" | "rewind" | "ignore" };

export function keyAction(
  key: ComposerKey,
  suggesting: boolean,
  empty: boolean,
  working: boolean,
  repeated: boolean,
): KeyAction {
  if (suggesting) {
    switch (key) {
      case "up":
        return { kind: "move", delta: -1 };
      case "down":
        return { kind: "move", delta: 1 };
      case "tab":
      case "enter":
        return { kind: "insert" };
      case "escape":
        return { kind: "close" };
      case "shiftEnter":
        return { kind: "ignore" };
    }
  }
  if (key === "enter") return { kind: "send" };
  if (key === "escape" && working) return { kind: "interrupt" };
  if (key === "escape" && repeated) return { kind: "rewind" };
  if (key === "up" && empty) return { kind: "recall" };
  return { kind: "ignore" };
}

// The longest pause between the two presses of Esc Esc, in milliseconds.
export const ESCAPE_REPEAT_MS = 600;

/** Esc pressed twice in quick succession, as Claude Code's Esc Esc. */
export class EscapeRepeat {
  private last: number | null = null;

  press(now: number): boolean {
    if (this.last !== null && now - this.last <= ESCAPE_REPEAT_MS) {
      this.last = null;
      return true;
    }
    this.last = now;
    return false;
  }
}
