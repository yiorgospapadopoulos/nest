import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../../test/fakeApi.ts";
import { artifactContent } from "../../test/fixtures.ts";
import { frameIn, openChat, openHistory, plan } from "../../test/artifacts.ts";
import { withCsp } from "./html.ts";

const PAGE = '<!doctype html><title>Rollout plan</title><pre id="nest-md"># Plan 3</pre>';

async function openPlan() {
  const api = fakeApi();
  api.artifacts.mockResolvedValue([plan]);
  api.markArtifactSeen.mockResolvedValue({ ...plan, seen: true });
  api.artifactVersion.mockResolvedValue(
    artifactContent({ artifact_id: "a1", version: 3, title: "Rollout plan", page: PAGE }),
  );
  const rendered = await openChat({ api });
  await openHistory(rendered);
  await rendered.user.click(await screen.findByRole("button", { name: /^Rollout plan/ }));
  const sheet = await screen.findByRole("dialog", { name: "Rollout plan" });
  return { ...rendered, sheet };
}

afterEach(() => {
  delete window.__TAURI__;
  vi.restoreAllMocks();
});

describe("the artifact frame in the desktop app", () => {
  it("loads the page from its own address, so its scripts keep the artifact policy", async () => {
    const invoke = vi.fn((command: string) =>
      Promise.resolve(command === "stage_artifact" ? "nest-artifact://localhost/abc" : null),
    );
    window.__TAURI__ = { core: { invoke }, event: { listen: vi.fn() } };
    const { sheet, unmount } = await openPlan();

    await waitFor(() => {
      expect(frameIn(sheet).getAttribute("src")).toBe("nest-artifact://localhost/abc");
    });
    const frame = frameIn(sheet);
    expect(frame.hasAttribute("srcdoc")).toBe(false);
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(invoke).toHaveBeenCalledWith("stage_artifact", { html: withCsp(PAGE) });

    unmount();
    expect(invoke).toHaveBeenCalledWith("release_artifact", {
      url: "nest-artifact://localhost/abc",
    });
  });

  it("keeps srcdoc everywhere else", async () => {
    const { sheet } = await openPlan();

    await waitFor(() => {
      expect(frameIn(sheet).getAttribute("srcdoc")).toBe(withCsp(PAGE));
    });
    expect(frameIn(sheet).hasAttribute("src")).toBe(false);
  });
});
