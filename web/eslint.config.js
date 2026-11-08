import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

// The desktop app draws its own screens, ported from the Mac's (B117): src/desktop imports
// no phone screen and no phone sheet. These modules under src/screens are pure logic (no
// JSX, no CSS) and stay shared.
const DESKTOP_SHARED = [
  "screens/approvals/hooks.ts",
  "screens/artifacts/bridge.ts",
  "screens/artifacts/files.ts",
  "screens/artifacts/html.ts",
  "screens/artifacts/view.ts",
  "screens/chat/ansi.ts",
  "screens/chat/earlier.ts",
  "screens/chat/images.ts",
  "screens/chat/localCommands.ts",
  "screens/chat/options.ts",
  "screens/chat/place.ts",
  "screens/chat/prView.ts",
  "screens/chat/prWork.ts",
  "screens/chat/scrollFollow.ts",
  "screens/chat/start.ts",
  "screens/chat/thumbnails.ts",
  "screens/chat/useAutopilot.ts",
  "screens/chat/useCompactAt.ts",
  "screens/chat/useJumpOnSend.ts",
  "screens/chat/useStopTask.ts",
  "screens/chat/useSuggestions.ts",
  "screens/chat/virtualRows.ts",
  "screens/pixies/habits.ts",
  "screens/inbox/needsLine.ts",
  "screens/pixies/motion.ts",
  "screens/pixies/options.ts",
  "screens/pixies/pending.ts",
  "screens/pixies/templates.ts",
  "screens/pixies/tones.ts",
  "screens/settings/accountText.ts",
  "screens/settings/configText.ts",
  "screens/settings/featureNew.ts",
  "screens/settings/featureText.ts",
  "screens/settings/perfText.ts",
  "screens/settings/usageText.ts",
  "screens/settings/useUsage.ts",
];

// A regex, as gitignore patterns cannot let a file through once its folder is excluded.
/** @param {string[]} allowed */
function desktopImports(allowed) {
  const escaped = allowed.map((path) => path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const open = escaped.filter((path) => path.startsWith("screens/")).map((p) => p.slice(8));
  const sheets = escaped.filter((path) => path.startsWith("ui/")).map((p) => p.slice(3));
  const except = (/** @type {string[]} */ names) =>
    names.length === 0 ? "" : `(?!(?:${names.join("|")})$)`;
  return {
    "no-restricted-imports": [
      "error",
      {
        patterns: [
          {
            regex: `(^|/)(screens/${except(open)}|ui/${except(sheets)}Sheet)`,
            message:
              "The desktop app draws its own screens (B117): port the Mac's view into src/desktop, or add a pure logic module (no JSX, no CSS) to DESKTOP_SHARED.",
          },
        ],
      },
    ],
  };
}

export default defineConfig([
  globalIgnores(["dist", "coverage", "src/generated"]),
  {
    files: ["**/*.{js,ts,tsx}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.strictTypeChecked,
      tseslint.configs.stylisticTypeChecked,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      prettier,
    ],
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
      parserOptions: {
        projectService: {
          allowDefaultProject: ["eslint.config.js"],
          defaultProject: "tsconfig.node.json",
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  { files: ["src/desktop/**/*.{ts,tsx}"], rules: desktopImports(DESKTOP_SHARED) },
]);
