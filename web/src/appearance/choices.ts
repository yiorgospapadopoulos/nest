// The appearance choices: theme, accent and message bubble. Kept apart from the DOM code, so
// the build can write the script that applies them before first paint.

export const THEMES = ["auto", "light", "dark"] as const;
export const ACCENTS = [
  { id: "graphite", label: "Graphite", light: "#2b2b2e", dark: "#e6e6e9" },
  { id: "ocean", label: "Ocean", light: "#2c6a9a", dark: "#79b4e3" },
  { id: "teal", label: "Teal", light: "#1f7a78", dark: "#5cc4bf" },
  { id: "moss", label: "Moss", light: "#55702f", dark: "#a5c26f" },
  { id: "clay", label: "Clay", light: "#a5573a", dark: "#e39a78" },
  { id: "rose", label: "Rose", light: "#a34a62", dark: "#e293a9" },
] as const;
export const BUBBLES = ["accent", "neutral"] as const;

export interface Appearance {
  theme: (typeof THEMES)[number];
  accent: (typeof ACCENTS)[number]["id"];
  bubble: (typeof BUBBLES)[number];
}

export const DEFAULT_APPEARANCE: Appearance = {
  theme: "auto",
  accent: "graphite",
  bubble: "accent",
};

export const STORAGE_KEY = "nest.appearance";
