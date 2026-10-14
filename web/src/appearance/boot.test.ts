import { afterEach, describe, expect, it } from "vitest";
import { memoryStorage } from "../test/render.tsx";
import { applyAppearance, loadAppearance, STORAGE_KEY } from "./appearance.ts";
import { appearanceBootScript, themeColorTags } from "./boot.ts";

const COLORS = { light: "#eeeeec", dark: "#0c0c0d" };

/** The root's attributes and the theme colors after `apply`, on a fresh page. */
function pageAfter(apply: () => void) {
  const root = document.documentElement;
  for (const name of root.getAttributeNames()) root.removeAttribute(name);
  document.head.innerHTML = themeColorTags(COLORS);
  apply();
  return {
    attributes: Object.fromEntries(root.getAttributeNames().map((n) => [n, root.getAttribute(n)])),
    colors: [...document.querySelectorAll('meta[name="theme-color"]')].map((m) =>
      m.getAttribute("content"),
    ),
  };
}

function boot(saved: string | null) {
  const storage = memoryStorage();
  if (saved !== null) storage.setItem(STORAGE_KEY, saved);
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
  runInline(appearanceBootScript());
  return storage;
}

/** Runs the script as the page's inline <script> tag does. */
function runInline(script: string): void {
  // eslint-disable-next-line @typescript-eslint/no-implied-eval -- our own script, as built
  const run = new Function(script) as () => void;
  run();
}

afterEach(() => {
  document.head.innerHTML = "";
});

describe("the appearance before first paint", () => {
  it.each([
    null,
    "{}",
    JSON.stringify({ theme: "dark", accent: "teal", bubble: "neutral", glass: "smoke" }),
    JSON.stringify({ theme: "light", accent: "graphite", bubble: "accent", glass: "clear" }),
    JSON.stringify({ theme: "auto", accent: "rose", glass: "deep" }),
    JSON.stringify({ theme: "sepia", accent: "purple", bubble: 3, glass: "sand" }),
    JSON.stringify({ theme: "constructor", accent: "toString" }),
    "null",
    "5",
    "not json",
  ])("matches what the app applies for %s", (saved) => {
    let storage = memoryStorage();
    const booted = pageAfter(() => {
      storage = boot(saved);
    });
    const applied = pageAfter(() => {
      applyAppearance(
        document.documentElement,
        loadAppearance(() => storage),
      );
    });

    expect(booted).toEqual(applied);
  });

  it("uses the appearance saved before the rename until the app moves it (B43)", () => {
    const storage = memoryStorage();
    storage.setItem("harness.appearance", JSON.stringify({ theme: "dark", accent: "teal" }));
    Object.defineProperty(window, "localStorage", { configurable: true, value: storage });

    const booted = pageAfter(() => {
      runInline(appearanceBootScript());
    });

    expect(booted.attributes).toEqual({ "data-theme": "dark", "data-accent": "teal" });
    expect(booted.colors).toEqual([COLORS.dark, COLORS.dark]);
  });

  it("leaves the page as it is when storage cannot be read", () => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new Error("SecurityError");
      },
    });

    expect(
      pageAfter(() => {
        runInline(appearanceBootScript());
      }),
    ).toEqual({
      attributes: {},
      colors: [COLORS.light, COLORS.dark],
    });
  });
});
