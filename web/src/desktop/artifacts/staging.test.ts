// Ported from the phone reader's frame tests (screens/artifacts/ArtifactReader.test.tsx), with
// the fallback cases that test does not cover.
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useStagedPage } from "./staging.ts";

const PAGE = '<!doctype html><title>Rollout plan</title><pre id="nest-md"># Plan 3</pre>';
const URL = "nest-artifact://localhost/abc";

function desktop(stage: () => Promise<unknown>) {
  const invoke = vi.fn((command: string) =>
    command === "stage_artifact" ? stage() : Promise.resolve(null),
  );
  window.__TAURI__ = { core: { invoke }, event: { listen: vi.fn() } };
  return invoke;
}

afterEach(() => {
  delete window.__TAURI__;
  vi.restoreAllMocks();
});

describe("the artifact frame's page", () => {
  it("loads from its own address in the desktop app, and is released when the frame goes", async () => {
    const invoke = desktop(() => Promise.resolve(URL));
    const { result, unmount } = renderHook(() => useStagedPage(PAGE));
    // Nothing loads while the page is staged: no srcdoc under the window's policy.
    expect(result.current).toEqual({});
    await waitFor(() => {
      expect(result.current).toEqual({ src: URL });
    });
    expect(invoke).toHaveBeenCalledWith("stage_artifact", { html: PAGE });

    unmount();
    expect(invoke).toHaveBeenCalledWith("release_artifact", { url: URL });
  });

  it("falls back to srcdoc when staging fails", async () => {
    desktop(() => Promise.reject(new Error("no scheme")));
    const { result } = renderHook(() => useStagedPage(PAGE));
    await waitFor(() => {
      expect(result.current).toEqual({ srcDoc: PAGE });
    });
  });

  it("keeps srcdoc outside the desktop app", () => {
    const { result } = renderHook(() => useStagedPage(PAGE));
    expect(result.current).toEqual({ srcDoc: PAGE });
  });

  it("releases a page staged after its frame went", async () => {
    let finish: (url: string) => void = () => undefined;
    const invoke = desktop(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { unmount } = renderHook(() => useStagedPage(PAGE));
    unmount();
    await act(async () => {
      finish(URL);
      await Promise.resolve();
    });
    expect(invoke).toHaveBeenCalledWith("release_artifact", { url: URL });
  });

  it("stages a new page and never shows the old address for it", async () => {
    let count = 0;
    desktop(() => Promise.resolve(`${URL}${String(++count)}`));
    const { result, rerender } = renderHook(({ page }) => useStagedPage(page), {
      initialProps: { page: PAGE },
    });
    await waitFor(() => {
      expect(result.current).toEqual({ src: `${URL}1` });
    });
    rerender({ page: `${PAGE}<p>2</p>` });
    expect(result.current).toEqual({});
    await waitFor(() => {
      expect(result.current).toEqual({ src: `${URL}2` });
    });
  });
});
