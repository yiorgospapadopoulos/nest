// The appearance choices: theme, glass, accent, message bubble and wallpaper. Kept apart
// from the DOM code, so the build can write the script that applies them before first paint.

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
