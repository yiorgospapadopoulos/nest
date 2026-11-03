// A pixie row keeps its @handle exactly when the Mac's would: widths are the Mac's SF
// measures (NSFont.systemFont 12, Leader at 10 medium plus its 5 px sides) drawn in Inter.
import { act, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { INTER_OVER_SF, showsHandle, useShowsHandle } from "./rowFit.ts";

const inter = (sf: number) => sf * INTER_OVER_SF;
// The default sidebar (236) less the row's insets, sprite slot and gap.
const DEFAULT = 236 - 15 - 18 - 8 - 16;
const LEADER = 43.8;

describe("a pixie row's handle", () => {
  it("shows for the default leader whose row fits on the Mac", () => {
    // 54.8 + 6 + 43.8 + 6 + 66.1 = 176.7 of 179 on the Mac.
    expect(
      showsHandle({ name: inter(54.8), leader: LEADER, handle: inter(66.1), available: DEFAULT }),
    ).toBe(true);
  });

  it("gives way where the Mac's does, before the name is cut", () => {
    // 54.8 + 6 + 43.8 + 6 + 79.0 = 189.6: the Mac hides "@new-pixie-2" too.
    expect(
      showsHandle({ name: inter(54.8), leader: LEADER, handle: inter(79.0), available: DEFAULT }),
    ).toBe(false);
    expect(
      showsHandle({ name: inter(54.8), leader: null, handle: inter(79.0), available: DEFAULT }),
    ).toBe(true);
    // Hovered, the row's ⋯ takes 21 more pixels.
    expect(
      showsHandle({ name: inter(54.8), leader: LEADER, handle: inter(66.1), available: 158 }),
    ).toBe(false);
  });
});

// What each part measures, by class; jsdom lays nothing out.
const widths: Record<string, number> = {};
const observers: { targets: Set<Element>; callback: () => void }[] = [];

function Row() {
  const label = useRef<HTMLSpanElement>(null);
  const shown = useShowsHandle(label, "New pixie @new-pixie");
  return (
    <span ref={label} className="px-label" data-testid="label">
      <span className="px-name">New pixie</span>
      <span className={shown ? "px-slug" : "px-slug gone"}>@new-pixie</span>
    </span>
  );
}

function stubLayout() {
  const width = (el: Element) => {
    const name = [...el.classList].find((c) => c in widths);
    return name === undefined ? 0 : (widths[name] ?? 0);
  };
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockImplementation(function (
    this: HTMLElement,
  ) {
    return width(this);
  });
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function (
    this: HTMLElement,
  ) {
    return width(this);
  });
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(function (
    this: HTMLElement,
  ) {
    return width(this);
  });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      targets = new Set<Element>();
      readonly callback: () => void;
      constructor(callback: () => void) {
        this.callback = callback;
        observers.push(this);
      }
      observe(target: Element) {
        this.targets.add(target);
      }
      disconnect() {
        this.targets.clear();
      }
    },
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  observers.length = 0;
});

describe("measuring a pixie row", () => {
  it("measures again when the text's size changes but the row's does not", () => {
    stubLayout();
    // First measured in a wider fallback, before Inter loaded.
    Object.assign(widths, { "px-label": DEFAULT, "px-name": 80, "px-slug": 110 });
    render(<Row />);
    expect(screen.getByText("@new-pixie")).toHaveClass("gone");
    // Inter arrives: the handle shrinks, the label keeps its width.
    Object.assign(widths, { "px-name": inter(54.8), "px-slug": inter(66.1) });
    const handle = screen.getByText("@new-pixie");
    act(() => {
      for (const o of observers) if (o.targets.has(handle)) o.callback();
    });
    expect(screen.getByText("@new-pixie")).not.toHaveClass("gone");
  });
});
