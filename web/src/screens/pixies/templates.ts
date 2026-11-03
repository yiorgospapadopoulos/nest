import type { Mascot } from "../../api/types.ts";

// One-tap starters while the user has no pixies; nothing is created without the tap (D072).
export const TEMPLATES: readonly { name: string; mascot: Mascot; soul: string }[] = [
  {
    name: "Reviewer",
    mascot: "moth",
    soul:
      "You review code changes. Look for bugs, missing tests and unclear names first, " +
      "style last. Say what you checked, then list problems by severity with file and line.",
  },
  {
    name: "Tester",
    mascot: "star",
    soul:
      "You test changes. Find how the project runs its tests, run them, add missing " +
      "cases for the change, and report what passed, what failed and why.",
  },
];

// The colour a new pixie gets.
export const DEFAULT_COLOR = "#8B7CF6";
