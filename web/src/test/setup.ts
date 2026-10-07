import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
  // The app keeps its route in the address; every test starts at the root. Build script
  // tests run without a window.
  if (typeof window !== "undefined") window.history.replaceState(null, "", "/");
});
