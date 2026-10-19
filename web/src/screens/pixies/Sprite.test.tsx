import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defined } from "../../test/defined.ts";
import { reduceMotion } from "../../test/motion.ts";
import { MASCOT_SPRITES } from "../../generated/mascots.ts";
import { phaseOffset } from "./motion.ts";
import { MASCOTS } from "./options.ts";
import { Sprite, WorkingDot } from "./Sprite.tsx";

// The spec both apps follow (B48): what a working sprite shows `t` ms into its clock.
function frameAt(t: number): { dy: number; blink: boolean } {
  const step = Math.floor(t / 170) % 4;
  const up = step === 1 || step === 2;
  return { dy: up ? -1 : 0, blink: up && Math.floor(t / 680) % 3 === 2 };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const sprite = (name = "bluebell") => screen.getByRole("img", { name });

// Every drawn cell as "x,y fill opacity", a rect of width n standing for n cells in a row.
function painted(group: Element | null): string[] {
  return [...(group?.querySelectorAll(":scope > rect") ?? [])].flatMap((r) => {
    const x = Number(r.getAttribute("x"));
    const y = Number(r.getAttribute("y"));
    expect(r).toHaveAttribute("height", "1");
    const tone = `${String(r.getAttribute("fill"))} ${r.getAttribute("fill-opacity") ?? "1"}`;
    return Array.from(
      { length: Number(r.getAttribute("width")) },
      (_, i) => `${String(x + i)},${String(y)} ${tone}`,
    );
  });
}

describe("a pixie's sprite at rest and at work (B48, B89)", () => {
  it("stays perfectly still while idle, square on its 14 by 14 grid", () => {
    render(<Sprite mascot="bluebell" color="#E5484D" size={24} />);
    const svg = sprite();
    expect(svg).not.toHaveClass("pxwork");
    expect(svg.style.getPropertyValue("--pxph")).toBe("");
    expect(svg.querySelector(".pxlid")).toBeNull();
    expect(svg).toHaveAttribute("width", "24");
    expect(svg).toHaveAttribute("height", "24");
    expect(svg).toHaveAttribute("viewBox", "0 0 14 14");
  });

  it("draws each cell in its tone of the pixie's colour and leaves empty cells out", () => {
    // The tones of #E5484D, worked by hand (see tones.test.ts).
    const tones: Record<string, string> = {
      "#": "#E5484D 1",
      "+": "#A03236 1",
      o: "#F7C8CA 1",
      "*": "#F19A9D 0.85",
      e: "#221E29 1",
      k: "#221E29 1",
    };
    for (const mascot of MASCOTS) {
      const { unmount } = render(<Sprite mascot={mascot} color="#E5484D" size={28} />);
      const expected = MASCOT_SPRITES[mascot].flatMap((row, y) =>
        Array.from({ length: row.length }, (_, x) => row.charAt(x)).flatMap((code, x) =>
          code === "." ? [] : [`${String(x)},${String(y)} ${defined(tones[code])}`],
        ),
      );
      expect(painted(sprite(mascot).querySelector(".pxhop")).sort(), mascot).toEqual(
        expected.sort(),
      );
      unmount();
    }
  });

  it("offers every mascot in the picker, in the design's order", () => {
    expect(MASCOTS).toEqual(Object.keys(MASCOT_SPRITES));
  });

  it("joins a row's run of one tone into a single rect", () => {
    render(<Sprite mascot="bluebell" color="#E5484D" size={24} />);
    // Row 0 is "....######....": one rect six cells wide.
    const top = [...sprite().querySelectorAll(".pxhop > rect[y='0']")];
    expect(top).toHaveLength(1);
    expect(top[0]).toHaveAttribute("x", "4");
    expect(top[0]).toHaveAttribute("width", "6");
  });

  it("hops and blinks while working, from its own phase, drawing its eyes in its colour", () => {
    render(<Sprite mascot="bluebell" color="#E5484D" size={24} working phaseKey="scribe" />);
    const svg = sprite();
    expect(svg).toHaveClass("pxwork");
    expect(svg.style.getPropertyValue("--pxph")).toBe(`-${String(phaseOffset("scribe"))}ms`);
    // The same box: the hop draws above it rather than growing it.
    expect(svg).toHaveAttribute("width", "24");
    expect(svg).toHaveAttribute("height", "24");
    expect(svg).toHaveAttribute("overflow", "visible");
    // Bluebell's eyes are the two "e" cells of row 5, ".oeooooeo.".
    expect(painted(svg.querySelector(".pxhop > .pxlid"))).toEqual([
      "4,5 #E5484D 1",
      "9,5 #E5484D 1",
    ]);
  });

  it("gives every mascot eyes to blink", () => {
    for (const mascot of MASCOTS) {
      const { unmount } = render(<Sprite mascot={mascot} color="#0090FF" size={24} working />);
      const lid = painted(sprite(mascot).querySelector(".pxlid"));
      const eyes = MASCOT_SPRITES[mascot].join("").split("e").length - 1;
      expect(lid.length, mascot).toBe(eyes);
      expect(eyes, mascot).toBeGreaterThan(0);
      unmount();
    }
  });

  it("does not move under Reduce Motion, and follows the setting as it changes", () => {
    const motion = reduceMotion(true);
    const { unmount } = render(<Sprite mascot="bluebell" color="#E5484D" size={24} working />);
    expect(sprite()).not.toHaveClass("pxwork");
    expect(sprite().querySelector(".pxlid")).toBeNull();
    motion.flip(false);
    expect(sprite()).toHaveClass("pxwork");
    motion.flip(true);
    expect(sprite()).not.toHaveClass("pxwork");
    unmount();
    expect(motion.listeners.size).toBe(0);
  });

  it("moves where the browser cannot tell the setting", () => {
    vi.stubGlobal("matchMedia", undefined);
    const { unmount } = render(<Sprite mascot="bluebell" color="#E5484D" size={24} working />);
    expect(sprite()).toHaveClass("pxwork");
    unmount();
  });
});

describe("the working mark beside a still sprite (B48, B80)", () => {
  it("shows only for work under Reduce Motion, where the sprite stays still", () => {
    reduceMotion(true);
    const { container, rerender } = render(<WorkingDot working />);
    expect(container.querySelector(".ff")).toBeInTheDocument();
    rerender(<WorkingDot working={false} />);
    expect(container.querySelector(".ff")).toBeNull();
  });

  it("stays away while the sprite itself shows the work", () => {
    reduceMotion(false);
    const { container } = render(<WorkingDot working />);
    expect(container.querySelector(".ff")).toBeNull();
  });
});

describe("the stylesheet's keyframes (B48)", () => {
  const sheet = document.createElement("style");
  sheet.textContent = readFileSync("src/styles/screens.css", "utf8");
  document.head.append(sheet);
  const rules = [...defined(sheet.sheet).cssRules];
  const keyframes = (name: string) =>
    defined(
      rules.find((r): r is CSSKeyframesRule => r instanceof CSSKeyframesRule && r.name === name),
    );
  // The value a step-end animation shows at `progress` (0 to 1): its last keyframe so far.
  const valueAt = (rule: CSSKeyframesRule, property: string, progress: number) => {
    let value = "";
    let latest = -1;
    for (const frame of [...rule.cssRules] as CSSKeyframeRule[]) {
      for (const at of frame.keyText.split(",").map((text) => parseFloat(text) / 100)) {
        if (at <= progress && at > latest) {
          latest = at;
          value = frame.style.getPropertyValue(property);
        }
      }
    }
    return value;
  };
  const hop = keyframes("pxhop");
  const lid = keyframes("pxblink");

  it("match the spec at every 10 ms of the blink cycle", () => {
    for (let t = 0; t < 2040; t += 10) {
      const frame = frameAt(t);
      const up = valueAt(hop, "transform", (t % 680) / 680) === "translateY(-1px)";
      expect(up ? -1 : 0, `hop at ${String(t)} ms`).toBe(frame.dy);
      const shut = valueAt(lid, "opacity", t / 2040) === "1";
      expect(shut, `lids at ${String(t)} ms`).toBe(frame.blink);
    }
  });

  it("run in hard steps on the shared clock, from each sprite's phase", () => {
    const style = (selector: string) =>
      defined(
        rules.find(
          (r): r is CSSStyleRule => r instanceof CSSStyleRule && r.selectorText === selector,
        ),
      ).style;
    for (const [selector, name, ms] of [
      [".pxwork .pxhop", "pxhop", "680ms"],
      [".pxwork .pxlid", "pxblink", "2040ms"],
    ] as const) {
      const s = style(selector);
      expect(s.getPropertyValue("animation-name")).toBe(name);
      expect(s.getPropertyValue("animation-duration")).toBe(ms);
      expect(s.getPropertyValue("animation-timing-function")).toBe("step-end");
      expect(s.getPropertyValue("animation-iteration-count")).toBe("infinite");
      expect(s.getPropertyValue("animation-delay")).toBe("var(--pxph)");
    }
    expect(style(".pxlid").getPropertyValue("opacity")).toBe("0");
  });
});
