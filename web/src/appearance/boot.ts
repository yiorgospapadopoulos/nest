// What the page's <head> gets at build time: the theme colors, and a script that applies the
// saved appearance before the first paint, as applyAppearance does once the app runs.
// Free of DOM types: the build (vite.config.ts) imports it.

import { ACCENTS, DEFAULT_APPEARANCE, STORAGE_KEY } from "./choices.ts";

// Where the appearance was saved before the rename to Nest (B43), until the app moves it.
const LEGACY_STORAGE_KEY = "harness.appearance";

export interface Colors {
  light: string;
  dark: string;
}

/**
 * A theme-color per color scheme. Each carries both colors, so a chosen theme can set
 * both to its own color and Auto can put each one back.
 */
export function themeColorTags(colors: Colors): string {
  const tag = (scheme: keyof Colors) =>
    `<meta name="theme-color" content="${colors[scheme]}" media="(prefers-color-scheme: ${scheme})" ` +
    `data-scheme="${scheme}" data-light="${colors.light}" data-dark="${colors.dark}" />`;
  return [tag("light"), tag("dark")].join("\n    ");
}

/** The script, without its tag; any failure leaves the page as the stylesheets make it. */
export function appearanceBootScript(): string {
  const others = (ids: readonly string[], fallback: string) =>
    JSON.stringify(ids.filter((id) => id !== fallback));
  const d = DEFAULT_APPEARANCE;
  return `(function () {
  try {
    var raw =
      localStorage.getItem(${JSON.stringify(STORAGE_KEY)}) ||
      localStorage.getItem(${JSON.stringify(LEGACY_STORAGE_KEY)});
    var saved = JSON.parse(raw || "{}") || {};
    var root = document.documentElement;
    var pick = function (list, value) {
      return list.indexOf(value) >= 0 ? value : null;
    };
    var theme = pick(["light", "dark"], saved.theme);
    var accent = pick(${others(
      ACCENTS.map((a) => a.id),
      d.accent,
    )}, saved.accent);
    if (theme) root.setAttribute("data-theme", theme);
    if (accent) root.setAttribute("data-accent", accent);
    if (saved.bubble === "neutral") root.setAttribute("data-bubble", "neutral");
    var metas = document.querySelectorAll('meta[name="theme-color"][data-scheme]');
    for (var i = 0; theme && i < metas.length; i++) {
      metas[i].setAttribute("content", metas[i].getAttribute("data-" + theme));
    }
  } catch (error) {
    // Left to the app, which applies the appearance once it runs.
  }
})();`;
}
