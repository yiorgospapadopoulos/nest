// Theme, accent and message bubble, applied through the data attributes of the generated
// token CSS, and remembered on this device only. Choices an older version saved that B102
// removed are not read, and go at the next save.

import {
  ACCENTS,
  BUBBLES,
  DEFAULT_APPEARANCE,
  STORAGE_KEY,
  THEMES,
  type Appearance,
} from "./choices.ts";

export * from "./choices.ts";

function pick<T extends string>(options: readonly T[], value: unknown, fallback: T): T {
  return options.find((option) => option === value) ?? fallback;
}

/** The saved appearance; anything missing, invalid or unreadable falls back to defaults. */
export function loadAppearance(storage: () => Storage): Appearance {
  let saved: Record<string, unknown> = {};
  try {
    const parsed: unknown = JSON.parse(storage().getItem(STORAGE_KEY) ?? "{}");
    if (typeof parsed === "object" && parsed !== null) saved = parsed as Record<string, unknown>;
  } catch {
    // Private mode or corrupt data: use the defaults.
  }
  const d = DEFAULT_APPEARANCE;
  return {
    theme: pick(THEMES, saved.theme, d.theme),
    accent: pick(
      ACCENTS.map((a) => a.id),
      saved.accent,
      d.accent,
    ),
    bubble: pick(BUBBLES, saved.bubble, d.bubble),
  };
}

export function saveAppearance(storage: () => Storage, appearance: Appearance): void {
  try {
    storage().setItem(STORAGE_KEY, JSON.stringify(appearance));
  } catch {
    // Not saved; it still applies until the app is closed.
  }
}

export function applyAppearance(root: HTMLElement, appearance: Appearance): void {
  const set = (name: string, value: string | null) => {
    if (value === null) root.removeAttribute(name);
    else root.setAttribute(name, value);
  };
  set("data-theme", appearance.theme === "auto" ? null : appearance.theme);
  set("data-accent", appearance.accent === "graphite" ? null : appearance.accent);
  set("data-bubble", appearance.bubble === "neutral" ? "neutral" : null);
  // The browser's theme color follows a chosen theme; Auto keeps each scheme's own.
  for (const meta of root.ownerDocument.querySelectorAll<HTMLMetaElement>(
    'meta[name="theme-color"][data-scheme]',
  )) {
    const scheme = appearance.theme === "auto" ? meta.dataset.scheme : appearance.theme;
    meta.content = meta.getAttribute(`data-${String(scheme)}`) ?? meta.content;
  }
}
