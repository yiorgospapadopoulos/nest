/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { preventZoom } from "./noZoom.ts";

describe("the phone app does not zoom", () => {
  // Without these, iPhone zooms in whenever a text box under 16 points is tapped.
  it("caps the page scale", () => {
    const html = readFileSync("index.html", "utf8");
    const viewport = /name="viewport"\s+content="([^"]*)"/.exec(html)?.[1] ?? "";
    expect(viewport).toContain("maximum-scale=1");
    expect(viewport).toContain("user-scalable=no");
  });

  it.each(["gesturestart", "gesturechange"])("cancels a pinch's %s", (type) => {
    const target = new EventTarget();
    preventZoom(target);
    const pinch = new Event(type, { cancelable: true });
    target.dispatchEvent(pinch);
    expect(pinch.defaultPrevented).toBe(true);
  });
});
