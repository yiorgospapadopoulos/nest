// Regression (B117 audit, P1): a click on the pill's strip away from the sprites did
// nothing. As the Mac's IslandView.mouseUp, the whole strip takes the click: the figure
// under the pointer, else the strip, which opens Nest.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../test/fakeApi.ts";
import { callEntry, groupEntry, pixie } from "../test/fixtures.ts";
import { socketFactory } from "../test/fakeSocket.ts";
import { memoryStorage } from "../test/render.tsx";
import { browserBridge, type Bridge } from "./bridge.ts";
import { DesktopApp } from "./DesktopApp.tsx";

async function renderPill(api = fakeApi()) {
  const openInMain = vi.fn<Bridge["openInMain"]>().mockResolvedValue(undefined);
  const bridge: Bridge = { ...browserBridge({ search: "" }, null), openInMain };
  const storage = memoryStorage();
  const { container } = render(
    <DesktopApp
      bridge={bridge}
      api={api}
      connect={socketFactory().connect}
      location={{ protocol: "http:", host: "127.0.0.1:8765" }}
      storage={() => storage}
      pill
    />,
  );
  await waitFor(() => {
    expect(container.querySelector(".dk-pstrip")).not.toBeNull();
  });
  const strip = container.querySelector(".dk-pstrip");
  if (strip === null) throw new Error("no strip");
  return { strip, openInMain };
}

describe("the pill's strip", () => {
  it("opens Nest from a click anywhere on it", async () => {
    const { strip, openInMain } = await renderPill();
    fireEvent.click(strip);
    expect(openInMain).toHaveBeenCalledWith({ home: true });
  });

  // Regression (B117 VM check): open, the pill is wider than its strip, and a click on the
  // top row beside the strip did nothing.
  it("opens Nest from a click on the open pill's top row beside the strip", async () => {
    const { strip, openInMain } = await renderPill();
    const row = strip.parentElement;
    if (row === null || row.classList.contains("dk-pill")) throw new Error("no row");
    fireEvent.click(row);
    expect(openInMain).toHaveBeenCalledWith({ home: true });
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// Regression (B117 VM re-check): two pixies worked for 30 s and the pill stayed on Nightshade
// and Bluebell. The scene only moved on animation frames, which the engine can hold back
// for a window it does not count as shown; it steps on a timer too.
describe("the pill's pixies", () => {
  it("show even when no animation frame ever comes", async () => {
    vi.stubGlobal("requestAnimationFrame", () => 0);
    vi.stubGlobal("cancelAnimationFrame", () => undefined);
    const api = fakeApi();
    api.pixies.mockResolvedValue([pixie({ id: "p1", name: "Pip" })]);
    api.pixieGroups.mockResolvedValue({
      s1: [
        groupEntry({
          pixie_id: "p1",
          state: "running",
          calls: [callEntry({ pixie_id: "p1", state: "running", finished_at: null })],
        }),
      ],
    });
    await renderPill(api);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Pip, Working" })).toBeTruthy();
    });
  });
});
