/// <reference types="node" />
import { readFileSync } from "node:fs";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { defined } from "../test/defined.ts";
import { Fireflies } from "./Fireflies.tsx";

describe("Fireflies (B80)", () => {
  it("draws three dots, hidden from assistive technology unless labelled", () => {
    const { container } = render(<Fireflies />);
    const box = defined(container.querySelector<HTMLElement>(".ff"));
    expect(box).toHaveAttribute("aria-hidden", "true");
    expect(box).not.toHaveAttribute("role");
    expect(box.querySelectorAll("i")).toHaveLength(3);
  });

  it("names the work when it stands alone", () => {
    const { getByRole } = render(<Fireflies label="running" />);
    const box = getByRole("img", { name: "running" });
    expect(box).toHaveClass("ff");
    expect(box).not.toHaveAttribute("aria-hidden");
  });

  it("takes the height it is given, 12 by default", () => {
    const { container, rerender } = render(<Fireflies />);
    const box = () => defined(container.querySelector<HTMLElement>(".ff"));
    expect(box().style.getPropertyValue("--ffh")).toBe("12px");
    rerender(<Fireflies size={9} />);
    expect(box().style.getPropertyValue("--ffh")).toBe("9px");
  });
});

describe("the fireflies and row glow stylesheet (B80)", () => {
  const css = readFileSync("src/styles/base.css", "utf8");
  const sheet = document.createElement("style");
  sheet.textContent = css;
  document.head.append(sheet);
  const rules = [...defined(sheet.sheet).cssRules];
  const style = (selector: string, within = rules) =>
    defined(
      within.find(
        (r): r is CSSStyleRule => r instanceof CSSStyleRule && r.selectorText === selector,
      ),
    ).style;
  const keyframes = (name: string) =>
    defined(
      rules.find((r): r is CSSKeyframesRule => r instanceof CSSKeyframesRule && r.name === name),
    );

  // Each frame as [at, x, y, scale, opacity], in units of the 16 by 12 box.
  const UNIT =
    /^translate\(calc\((-?[\d.]+) \* var\(--u\)\), calc\((-?[\d.]+) \* var\(--u\)\)\) scale\(([\d.]+)\)$/;
  const frames = (name: string) =>
    ([...keyframes(name).cssRules] as CSSKeyframeRule[]).flatMap((frame) => {
      const [, x, y, scale] = defined(UNIT.exec(frame.style.getPropertyValue("transform")));
      return frame.keyText
        .split(",")
        .map((at) => [
          parseFloat(at),
          Number(x),
          Number(y),
          Number(scale),
          Number(frame.style.getPropertyValue("opacity")),
        ]);
    });
  const sorted = (rows: number[][]) => rows.sort((a, b) => (a[0] ?? 0) - (b[0] ?? 0));

  it("moves each dot as the spec says", () => {
    expect(sorted(frames("ff1"))).toEqual([
      [0, 0, 0, 1, 1],
      [30, 4, -4, 0.75, 0.55],
      [60, 6, 1, 1.15, 1],
      [100, 0, 0, 1, 1],
    ]);
    expect(sorted(frames("ff2"))).toEqual([
      [0, 0, 0, 0.8, 0.6],
      [40, -4, 5, 1.15, 1],
      [70, 3, 6, 0.9, 0.7],
      [100, 0, 0, 0.8, 0.6],
    ]);
    expect(sorted(frames("ff3"))).toEqual([
      [0, 0, 0, 1.1, 1],
      [50, -6, -5, 0.8, 0.55],
      [100, 0, 0, 1.1, 1],
    ]);
  });

  it("places and times each dot, glowing in the accent", () => {
    const dot = (n: number) => style(`.ff i:nth-child(${String(n)})`);
    expect([1, 2, 3].map((n) => [dot(n).left, dot(n).top, dot(n).animation])).toEqual([
      ["calc(1 * var(--u))", "calc(5 * var(--u))", "ff1 2.4s ease-in-out infinite"],
      ["calc(7 * var(--u))", "calc(1 * var(--u))", "ff2 2.9s ease-in-out infinite"],
      ["calc(12 * var(--u))", "calc(8 * var(--u))", "ff3 2.1s ease-in-out infinite"],
    ]);
    expect(style(".ff").color).toBe("var(--accent)");
    expect(style(".ff").getPropertyValue("--u")).toMatch(/^calc\(var\(--ffh\) ?\/ ?12\)$/);
    expect(style(".ff i").background).toBe("currentcolor");
    expect(style(".ff i").boxShadow).toBe(
      "0 0 calc(4 * var(--u)) calc(1.5 * var(--u)) currentcolor",
    );
    expect(style(".b-pri .ff").color).toBe("var(--on-accent)");
  });

  it("sweeps a band of accent across the row without catching taps", () => {
    const band = style(".rglow::after");
    expect(band.pointerEvents).toBe("none");
    expect(band.width).toBe("50%");
    expect(band.animation).toBe("rowsweep 1.8s ease-in-out infinite");
    expect(band.backgroundImage || band.background).toContain(
      "color-mix(in srgb, var(--accent) 24%, transparent)",
    );
    expect(style(".rglow").overflow).toBe("hidden");
    const sweep = [...keyframes("rowsweep").cssRules] as CSSKeyframeRule[];
    expect(sweep.map((f) => [f.keyText, f.style.transform])).toEqual([
      ["0%", "translateX(-100%)"],
      ["100%", "translateX(200%)"],
    ]);
  });

  it("holds the dots still and drops the glow under Reduce Motion", () => {
    const reduce = rules
      .filter((r): r is CSSMediaRule => r instanceof CSSMediaRule)
      .filter((r) => r.conditionText === "(prefers-reduced-motion: reduce)")
      .flatMap((r) => [...r.cssRules]);
    expect(style(".ff i", reduce).animation).toBe("none");
    expect(style(".rglow::after", reduce).display).toBe("none");
  });
});
