import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { defined } from "../test/defined.ts";
import { Dot, Pill } from "./bits.tsx";

describe("Dot (B80)", () => {
  it("draws fireflies 12 by 9 for the run tone, hidden like the dot", () => {
    const { container } = render(<Dot tone="run" />);
    const flies = defined(container.querySelector<HTMLElement>(".ff"));
    expect(flies).toHaveAttribute("aria-hidden", "true");
    expect(flies.style.getPropertyValue("--ffh")).toBe("9px");
    expect(container.querySelector(".dot")).toBeNull();
  });

  it.each(["wait", "rev", "fail", "done", "idle", "int"] as const)(
    "keeps the plain dot for the %s tone",
    (tone) => {
      const { container } = render(<Dot tone={tone} />);
      expect(container.querySelector(".dot")).toHaveClass(`s-${tone}`);
      expect(container.querySelector(".ff")).toBeNull();
    },
  );

  it("stays a plain running dot where it is kept", () => {
    const { container } = render(<Dot tone="run" plain />);
    expect(container.querySelector(".dot")).toHaveClass("s-run");
    expect(container.querySelector(".ff")).toBeNull();
  });

  it("names the status when given a label, as a dot or as fireflies", () => {
    const { rerender } = render(<Dot tone="fail" label="Failed" />);
    const dot = screen.getByRole("img", { name: "Failed" });
    expect(dot).toHaveClass("dot s-fail");
    expect(dot).toHaveAttribute("title", "Failed");
    expect(dot).not.toHaveAttribute("aria-hidden");

    rerender(<Dot tone="run" label="Running" />);
    const flies = screen.getByRole("img", { name: "Running" });
    expect(flies).toHaveClass("ff");
    expect(flies).toHaveAttribute("title", "Running");
  });
});

describe("Pill (B80)", () => {
  it("carries fireflies in place of its dot while running, in the run colours", () => {
    const { container } = render(<Pill tone="run" label="Working" />);
    const pill = defined(container.querySelector(".sp"));
    expect(pill).toHaveClass("s-run");
    expect(pill.firstElementChild).toHaveClass("ff");
    expect(pill).toHaveTextContent("Working");
  });

  it("keeps its dot for other tones", () => {
    const { container } = render(<Pill tone="wait" label="Needs sign-in" />);
    expect(container.querySelector(".sp > .dot.s-wait")).not.toBeNull();
  });
});
