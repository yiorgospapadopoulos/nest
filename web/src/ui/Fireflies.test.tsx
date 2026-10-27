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
