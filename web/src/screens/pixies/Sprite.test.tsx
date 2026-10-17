import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defined } from "../../test/defined.ts";
import { reduceMotion } from "../../test/motion.ts";
import { phaseOffset } from "./motion.ts";
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

const sprite = () => screen.getByRole("img", { name: "invader" });
const cells = (group: Element | null) =>
  [...(group?.querySelectorAll("rect") ?? [])].map(
    (r) => `${String(r.getAttribute("x"))},${String(r.getAttribute("y"))}`,
  );

describe("a pixie's sprite at rest and at work (B48)", () => {
  it("stays perfectly still while idle", () => {
    render(<Sprite mascot="invader" color="#E5484D" size={24} />);
    const svg = sprite();
    expect(svg).not.toHaveClass("pxwork");
    expect(svg.style.getPropertyValue("--pxph")).toBe("");
    expect(svg.querySelector(".pxlid")).toBeNull();
    expect(svg).toHaveAttribute("width", "24");
    expect(svg).toHaveAttribute("height", "20");
  });

  it("hops and blinks its eye holes while working, from its own phase", () => {
    render(<Sprite mascot="invader" color="#E5484D" size={24} working phaseKey="scribe" />);
    const svg = sprite();
    expect(svg).toHaveClass("pxwork");
    expect(svg.style.getPropertyValue("--pxph")).toBe(`-${String(phaseOffset("scribe"))}ms`);
    // The same box: the hop draws above it rather than growing it.
    expect(svg).toHaveAttribute("width", "24");
    expect(svg).toHaveAttribute("height", "20");
    expect(svg).toHaveAttribute("overflow", "visible");
    expect(cells(svg.querySelector(".pxhop > .pxlid"))).toEqual(["4,3", "7,3"]);
    expect(svg.querySelector(".pxlid rect")).toHaveAttribute("fill", "#E5484D");
  });

  it("lets a mascot without eye holes put its lone eye cells out instead", () => {
    const { rerender } = render(<Sprite mascot="robot" color="#0090FF" size={24} />);
    const svg = screen.getByRole("img", { name: "robot" });
    // The eyes are drawn in their own group at rest too, so nothing moves on start.
    expect(cells(svg.querySelector(".pxhop > .pxeye"))).toEqual(["4,4", "7,4"]);
    expect(svg.querySelector(".pxlid")).toBeNull();
    const all = svg.querySelectorAll("rect");
    rerender(<Sprite mascot="robot" color="#0090FF" size={24} working />);
    expect(svg).toHaveClass("pxwork");
    expect(svg.querySelectorAll("rect")).toHaveLength(all.length);
  });

  it("does not move under Reduce Motion, and follows the setting as it changes", () => {
    const motion = reduceMotion(true);
    const { unmount } = render(<Sprite mascot="invader" color="#E5484D" size={24} working />);
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
    const { unmount } = render(<Sprite mascot="invader" color="#E5484D" size={24} working />);
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
  const eye = keyframes("pxwink");

  it("match the spec at every 10 ms of the blink cycle", () => {
    for (let t = 0; t < 2040; t += 10) {
      const frame = frameAt(t);
      const up = valueAt(hop, "transform", (t % 680) / 680) === "translateY(-1px)";
      expect(up ? -1 : 0, `hop at ${String(t)} ms`).toBe(frame.dy);
      const shut = valueAt(lid, "opacity", t / 2040) === "1";
      expect(shut, `lids at ${String(t)} ms`).toBe(frame.blink);
      expect(valueAt(eye, "opacity", t / 2040) === "0", `eyes at ${String(t)} ms`).toBe(
        frame.blink,
      );
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
      [".pxwork .pxeye", "pxwink", "2040ms"],
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
