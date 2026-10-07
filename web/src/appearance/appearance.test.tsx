import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppearanceCard } from "../screens/account/AppearanceCard.tsx";
import { memoryStorage } from "../test/render.tsx";
import {
  applyAppearance,
  DEFAULT_APPEARANCE,
  loadAppearance,
  saveAppearance,
  STORAGE_KEY,
} from "./appearance.ts";

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

  it("saves quietly even when storage is unavailable", () => {
    const storage = memoryStorage();

    saveAppearance(() => storage, DEFAULT_APPEARANCE);
    saveAppearance(broken, DEFAULT_APPEARANCE);

    expect(storage.getItem(STORAGE_KEY)).toBe(JSON.stringify(DEFAULT_APPEARANCE));
  });

  it("sets and clears the token data attributes", () => {
    const root = document.createElement("div");

    applyAppearance(root, { theme: "light", accent: "teal", bubble: "neutral", wallpaper: "sage" });
    expect([root.dataset.theme, root.dataset.accent, root.dataset.bubble]).toEqual([
      "light",
      "teal",
      "neutral",
    ]);
    applyAppearance(root, DEFAULT_APPEARANCE);
    expect(root.attributes).toHaveLength(0);
  });

  it("renders the defaults without a provider", () => {
    render(<AppearanceCard />);

    fireEvent.click(screen.getByRole("button", { name: "Dark" }));

    expect(screen.getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "true");
  });
});
