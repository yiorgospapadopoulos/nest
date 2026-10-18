import { describe, expect, it } from "vitest";
import { mix, toneOf } from "./tones.ts";

describe("a sprite cell's tone (B89)", () => {
  // Worked by hand from #E5484D, per channel and rounded: shade 0.3 to black, light 0.7
  // and wing 0.45 to white.
  it("mixes each RGB channel towards another colour and rounds", () => {
    expect(mix("#E5484D", "#000000", 0.3)).toBe("#A03236");
    expect(mix("#E5484D", "#FFFFFF", 0.7)).toBe("#F7C8CA");
    expect(mix("#E5484D", "#FFFFFF", 0.45)).toBe("#F19A9D");
    expect(mix("#0090ff", "#FFFFFF", 0)).toBe("#0090FF");
    expect(mix("#0090FF", "#FFFFFF", 1)).toBe("#FFFFFF");
    // 0x01 + (0xFF - 0x01) * 0.5 = 128 exactly; 0x00 + 0xFF * 0.5 = 127.5 rounds up.
    expect(mix("#010000", "#FFFFFF", 0.5)).toBe("#808080");
  });

  it("draws the body in the pixie's colour and the eyes and ink in the ink", () => {
    expect(toneOf("#", "#E5484D")).toEqual({ fill: "#E5484D", opacity: 1 });
    expect(toneOf("e", "#E5484D")).toEqual({ fill: "#221E29", opacity: 1 });
    expect(toneOf("k", "#0090FF")).toEqual({ fill: "#221E29", opacity: 1 });
  });

  it("derives the shade, light and wing tint from the pixie's colour", () => {
    expect(toneOf("+", "#E5484D")).toEqual({ fill: "#A03236", opacity: 1 });
    expect(toneOf("o", "#E5484D")).toEqual({ fill: "#F7C8CA", opacity: 1 });
    expect(toneOf("*", "#E5484D")).toEqual({ fill: "#F19A9D", opacity: 0.85 });
  });

  it("draws nothing for an empty cell or a code it does not know", () => {
    expect(toneOf(".", "#E5484D")).toBeNull();
    expect(toneOf("x", "#E5484D")).toBeNull();
    expect(toneOf("", "#E5484D")).toBeNull();
  });
});
