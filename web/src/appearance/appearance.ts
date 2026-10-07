// Theme, glass, accent, message bubble and wallpaper, applied through the data attributes
// and classes of the generated token CSS, and remembered on this device only.

export const THEMES = ["auto", "light", "dark"] as const;
export const ACCENTS = [
  { id: "graphite", label: "Graphite", light: "#2b2b2e", dark: "#e6e6e9" },
  { id: "ocean", label: "Ocean", light: "#2c6a9a", dark: "#79b4e3" },
  { id: "teal", label: "Teal", light: "#1f7a78", dark: "#5cc4bf" },
  { id: "moss", label: "Moss", light: "#55702f", dark: "#a5c26f" },
  { id: "clay", label: "Clay", light: "#a5573a", dark: "#e39a78" },
  { id: "rose", label: "Rose", light: "#a34a62", dark: "#e293a9" },
] as const;
// The glass themes change the glass only (tint, blur, edges, depth, corners, density), never
// the layout. Their values live in the generated tokens; names and descriptions live here.
export const GLASSES = [
  {
    id: "clear",
    label: "Clear",
    description: "The base layer. Barely tinted, light blur, the most see-through.",
  },
  {
    id: "frosted",
    label: "Frosted",
    description: "Milky glass with a heavy blur. The most readable.",
  },
  {
    id: "smoke",
    label: "Smoke",
    description: "Neutral grey smoked glass, darkest in dark mode.",
  },
  { id: "bluegrey", label: "Blue Grey", description: "A cool slate tint, like glass in shade." },
  { id: "deep", label: "Deep", description: "Thick, heavily tinted glass with strong depth." },
] as const;
export const BUBBLES = ["accent", "neutral"] as const;
export const WALLPAPERS = ["stone", "sage", "sky", "slate"] as const;

export interface Appearance {
  theme: (typeof THEMES)[number];
  accent: (typeof ACCENTS)[number]["id"];
  bubble: (typeof BUBBLES)[number];
  wallpaper: (typeof WALLPAPERS)[number];
  glass: (typeof GLASSES)[number]["id"];
}

export const DEFAULT_APPEARANCE: Appearance = {
  theme: "auto",
  accent: "graphite",
  bubble: "accent",
  wallpaper: "stone",
  glass: "clear",
};

export const STORAGE_KEY = "harness.appearance";

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
    wallpaper: pick(WALLPAPERS, saved.wallpaper, d.wallpaper),
    glass: pick(
      GLASSES.map((g) => g.id),
      saved.glass,
      d.glass,
    ),
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
  // Clear is also the generated tokens' default, so it needs no attribute.
  set("data-glass", appearance.glass === "clear" ? null : appearance.glass);
}
