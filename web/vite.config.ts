import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import { pwa } from "./build/pwa.ts";

const tokens = fileURLToPath(new URL("./src/generated/tokens.css", import.meta.url));
const icons = fileURLToPath(new URL("./build/icons", import.meta.url));

export default defineConfig({
  plugins: [react(), pwa(tokens, icons)],
  build: {
    rolldownOptions: {
      input: {
        index: fileURLToPath(new URL("./index.html", import.meta.url)),
        sw: fileURLToPath(new URL("./src/pwa/sw.ts", import.meta.url)),
      },
      output: {
        // The service worker keeps a fixed name at the root, so its scope is the whole app.
        entryFileNames: (chunk) => (chunk.name === "sw" ? "sw.js" : "assets/[name]-[hash].js"),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text"],
      include: ["src/**/*.{ts,tsx}", "build/**/*.ts"],
      exclude: ["src/main.tsx", "**/*.test.{ts,tsx}", "src/**/*.d.ts", "src/generated/**"],
      thresholds: {
        lines: 100,
        branches: 100,
        functions: 100,
        statements: 100,
      },
    },
  },
});
