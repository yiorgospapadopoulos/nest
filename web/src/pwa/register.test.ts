import { afterEach, describe, expect, it, vi } from "vitest";
import { NAVIGATE } from "./navigate.ts";
import { registerServiceWorker } from "./register.ts";
import { NAVIGATE as WORKER_NAVIGATE } from "./serviceWorker.ts";

describe("registerServiceWorker", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("registers the worker at the root in production", async () => {
    const register = vi.fn(() => Promise.resolve({} as ServiceWorkerRegistration));

    await expect(registerServiceWorker({ serviceWorker: { register } }, true)).resolves.toBe(true);
    expect(register).toHaveBeenCalledWith("/sw.js", { scope: "/" });
  });

  it("skips development builds and browsers without service workers", async () => {
    const register = vi.fn();

    await expect(registerServiceWorker({ serviceWorker: { register } }, false)).resolves.toBe(
      false,
    );
    await expect(registerServiceWorker({}, true)).resolves.toBe(false);
    expect(register).not.toHaveBeenCalled();
  });

  it("reports a failed registration without throwing", async () => {
    const register = vi.fn(() => Promise.reject(new Error("insecure")));

    await expect(registerServiceWorker({ serviceWorker: { register } }, true)).resolves.toBe(false);
  });

  it("installs the worker into its global scope", async () => {
    const addEventListener = vi.fn<(type: string) => void>();
    vi.stubGlobal("self", { addEventListener });

    await import("./sw.ts");

    expect(addEventListener.mock.calls.map((call) => call[0])).toEqual([
      "install",
      "activate",
      "fetch",
      "push",
      "notificationclick",
    ]);
  });

  it("keeps the worker free of modules shared with the app", () => {
    // Shared modules become chunks that a classic worker script cannot import.
    const sources = import.meta.glob<string>("/src/**/*.{ts,tsx}", {
      query: "?raw",
      import: "default",
      eager: true,
    });
    const importers = Object.entries(sources)
      .filter(([path]) => !/\.test\.tsx?$/.test(path))
      .filter(([, text]) => text.includes('/serviceWorker.ts"'))
      .map(([path]) => path);

    expect(importers).toEqual(["/src/pwa/sw.ts"]);
    expect(WORKER_NAVIGATE).toBe(NAVIGATE);
  });
});
