import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppearancePage } from "../screens/settings/AppearancePage.tsx";
import { memoryStorage } from "../test/render.tsx";
import {
  applyAppearance,
  DEFAULT_APPEARANCE,
  GLASSES,
  loadAppearance,
  saveAppearance,
  STORAGE_KEY,
} from "./appearance.ts";
import { themeColorTags } from "./boot.ts";

const broken = () => {
  throw new Error("SecurityError");
};

describe("appearance", () => {
  it("loads saved choices and falls back on anything invalid", () => {
    const storage = memoryStorage();
    storage.setItem(
      STORAGE_KEY,
      JSON.stringify({ theme: "dark", accent: "purple", wallpaper: "sky" }),
    );

    expect(loadAppearance(() => storage)).toEqual({
      ...DEFAULT_APPEARANCE,
      theme: "dark",
      wallpaper: "sky",
    });
    for (const raw of ["not json", "5", "null"]) {
      storage.setItem(STORAGE_KEY, raw);
      expect(loadAppearance(() => storage)).toEqual(DEFAULT_APPEARANCE);
    }
    expect(loadAppearance(broken)).toEqual(DEFAULT_APPEARANCE);
  });

  it("loads the saved glass theme and falls back to Clear for an unknown one", () => {
    const storage = memoryStorage();

    storage.setItem(STORAGE_KEY, JSON.stringify({ glass: "smoke" }));
    expect(loadAppearance(() => storage).glass).toBe("smoke");
    for (const glass of ["sand", 3, null]) {
      storage.setItem(STORAGE_KEY, JSON.stringify({ glass }));
      expect(loadAppearance(() => storage).glass).toBe("clear");
    }
    expect(DEFAULT_APPEARANCE.glass).toBe("clear");
  });

  it("offers the five approved glass themes, Clear first, each described", () => {
    expect(GLASSES.map((glass) => glass.id)).toEqual([
      "clear",
      "frosted",
      "smoke",
      "bluegrey",
      "deep",
    ]);
    expect(GLASSES.map((glass) => glass.label)).toEqual([
      "Clear",
      "Frosted",
      "Smoke",
      "Blue Grey",
      "Deep",
    ]);
    for (const glass of GLASSES) expect(glass.description).toMatch(/^[A-Z].+\.$/);
  });

  it("saves quietly even when storage is unavailable", () => {
    const storage = memoryStorage();

    saveAppearance(() => storage, DEFAULT_APPEARANCE);
    saveAppearance(broken, DEFAULT_APPEARANCE);

    expect(storage.getItem(STORAGE_KEY)).toBe(JSON.stringify(DEFAULT_APPEARANCE));
  });

  it("sets and clears the token data attributes", () => {
    const root = document.createElement("div");

    applyAppearance(root, {
      theme: "light",
      accent: "teal",
      bubble: "neutral",
      wallpaper: "sage",
      glass: "deep",
    });
    expect([
      root.dataset.theme,
      root.dataset.accent,
      root.dataset.bubble,
      root.dataset.glass,
    ]).toEqual(["light", "teal", "neutral", "deep"]);
    applyAppearance(root, DEFAULT_APPEARANCE);
    expect(root.attributes).toHaveLength(0);
  });

  it("makes the theme color follow a chosen theme", () => {
    // A theme color the build did not write stays as it is.
    document.head.innerHTML =
      themeColorTags({ light: "#eeeeec", dark: "#0c0c0d" }) +
      '<meta name="theme-color" data-scheme="dark" content="#123456" />';
    const contents = () =>
      [...document.querySelectorAll('meta[name="theme-color"]')].map((m) =>
        m.getAttribute("content"),
      );

    applyAppearance(document.documentElement, { ...DEFAULT_APPEARANCE, theme: "dark" });
    expect(contents()).toEqual(["#0c0c0d", "#0c0c0d", "#123456"]);
    applyAppearance(document.documentElement, { ...DEFAULT_APPEARANCE, theme: "light" });
    expect(contents()).toEqual(["#eeeeec", "#eeeeec", "#123456"]);
    applyAppearance(document.documentElement, DEFAULT_APPEARANCE);
    expect(contents()).toEqual(["#eeeeec", "#0c0c0d", "#123456"]);
    document.head.innerHTML = "";
  });

  it("renders the defaults without a provider", () => {
    render(<AppearancePage />);

    fireEvent.click(screen.getByRole("button", { name: "Dark" }));

    expect(screen.getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Clear" })).toHaveAttribute("aria-pressed", "true");
  });
});
