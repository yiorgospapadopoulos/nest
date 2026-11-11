import { afterEach, expect, it, vi } from "vitest";
import type { ArtifactContent } from "../../api/types.ts";
import { browserBridge } from "../bridge.ts";
import { saveAs } from "./save.ts";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("saves an HTML artifact in a browser as bytes, never as a page", async () => {
  // B166: a text/html blob on Nest's own address, if the browser showed it instead of
  // downloading it, would run the agent's script as Nest.
  const blobs: Blob[] = [];
  vi.stubGlobal(
    "URL",
    Object.assign(URL, {
      createObjectURL: (blob: Blob) => {
        blobs.push(blob);
        return "blob:x";
      },
      revokeObjectURL: () => undefined,
    }),
  );
  const clicked: HTMLAnchorElement[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicked.push(this);
  });
  const content: ArtifactContent = {
    artifact_id: "a1",
    version: 1,
    kind: "html",
    title: "Report",
    content: "<script>alert(1)</script>",
    page: "<!doctype html>",
    size: 25,
    created_at: "2026-11-11T10:00:00Z",
    author: "agent",
    files: [],
  };

  const saved = await saveAs(content, browserBridge({ search: "" }, null));

  expect(saved).toBeNull();
  expect(clicked[0]?.download).toBe("Report.html");
  expect(blobs[0]?.type).toBe("application/octet-stream");
  expect(await blobs[0]?.text()).toBe("<script>alert(1)</script>");
});
