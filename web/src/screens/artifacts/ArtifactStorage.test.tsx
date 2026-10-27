import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { JsonObject } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { artifact, artifactContent } from "../../test/fixtures.ts";
import { systemDark } from "../../test/motion.ts";
import { memoryStorage } from "../../test/render.tsx";
import { STORAGE_KEY } from "../../appearance/appearance.ts";
import { succeed } from "./bridge.ts";
import { frameIn, openChat, openHistory, plan, showing } from "../../test/artifacts.ts";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("what a page stores, and files it saves (B88)", () => {
  const tracker = artifact({
    id: "t1",
    title: "Habit tracker",
    kind: "html",
    latest_version: 2,
    version_count: 2,
    seen: true,
  });

  /** The reader on the tracker, its page's mail, and ways to post as the page. */
  async function readingTracker(api = fakeApi()) {
    api.artifacts.mockResolvedValue([tracker]);
    api.artifactVersion.mockImplementation((id, version) =>
      Promise.resolve(
        artifactContent({
          artifact_id: id,
          version,
          kind: "html",
          title: "Habit tracker",
          content: `<p>Tracker ${String(version)}</p>`,
        }),
      ),
    );
    const rendered = await openChat({ api });
    await openHistory(rendered);
    await rendered.user.click(await screen.findByRole("button", { name: /^Habit tracker/ }));
    const sheet = await screen.findByRole("dialog", { name: "Habit tracker" });
    await showing(sheet, "Tracker 2");
    const page = frameIn(sheet).contentWindow;
    if (page === null) throw new Error("no window");
    const sent = vi.spyOn(page, "postMessage");
    const replies = () => sent.mock.calls.map(([reply]) => reply as unknown);
    const call = (id: string, method: string, params: unknown) => {
      act(() => {
        window.dispatchEvent(
          new MessageEvent("message", {
            data: { nest: 1, id, method, params },
            source: frameIn(sheet).contentWindow,
          }),
        );
      });
    };
    const changed = (payload: JsonObject) => {
      rendered.push({ id: null, type: "artifact.storage", payload });
    };
    return { ...rendered, api, sheet, replies, call, changed };
  }

  const refused = (id: string, code: string, message: string = expect.any(String) as string) => ({
    nest: 1,
    id,
    ok: false,
    error: { code, message },
  });
  const meta = (sheet: HTMLElement) => sheet.querySelector(".afmeta");

  it("shows nothing of page data while the page stored none", async () => {
    const api = fakeApi();
    const { sheet } = await readingTracker(api);
    expect(api.artifactStorage).toHaveBeenCalledWith("t1");
    expect(meta(sheet)).not.toHaveTextContent("stored");
    expect(within(sheet).queryByRole("button", { name: "Clear page data" })).toBeNull();
  });

  it("shows the stored size, and clears it after asking", async () => {
    const api = fakeApi();
    api.artifactStorage.mockResolvedValue({ items: { done: "1" }, size: 4200 });
    const { sheet, user, replies } = await readingTracker(api);
    await waitFor(() => {
      expect(meta(sheet)).toHaveTextContent("4.2 KB stored");
    });
    await user.click(within(sheet).getByRole("button", { name: "Clear page data" }));
    const ask = await screen.findByRole("alertdialog", { name: "Clear page data?" });
    await user.click(within(ask).getByRole("button", { name: "Clear" }));
    expect(api.clearArtifactStorage).toHaveBeenCalledWith("t1");
    await waitFor(() => {
      expect(meta(sheet)).not.toHaveTextContent("stored");
    });
    // The page hears of it from the daemon's event, not from the reader.
    expect(replies()).toEqual([]);
  });

  it("keeps the data and says so when it cannot be cleared", async () => {
    const api = fakeApi();
    api.artifactStorage.mockResolvedValue({ items: { done: "1" }, size: 10 });
    api.clearArtifactStorage.mockRejectedValueOnce(new Error("offline"));
    const { sheet, user } = await readingTracker(api);
    await user.click(await within(sheet).findByRole("button", { name: "Clear page data" }));
    await user.click(
      within(await screen.findByRole("alertdialog", { name: "Clear page data?" })).getByRole(
        "button",
        { name: "Clear" },
      ),
    );
    expect(await screen.findByText("Could not clear the page data")).toBeInTheDocument();
    expect(meta(sheet)).toHaveTextContent("10 bytes stored");
  });

  it("writes what the page stores and shows the new size", async () => {
    const api = fakeApi();
    api.writeArtifactStorage.mockResolvedValueOnce({ size: 2500 });
    const { sheet, replies, call } = await readingTracker(api);
    call("1", "storageWrite", { set: { mon: "done" }, remove: ["tue"] });
    await waitFor(() => {
      expect(replies()).toEqual([succeed("1", { size: 2500 })]);
    });
    expect(api.writeArtifactStorage).toHaveBeenCalledWith("t1", {
      set: { mon: "done" },
      remove: ["tue"],
    });
    expect(meta(sheet)).toHaveTextContent("2.5 KB stored");
  });

  it("answers quota over a cap, bad_request to bad keys, unavailable otherwise", async () => {
    const api = fakeApi();
    api.writeArtifactStorage
      .mockRejectedValueOnce(new ApiError(413, "Page data is limited to 2 MiB."))
      .mockRejectedValueOnce(new ApiError(422, "A key is 1 to 256 characters."))
      .mockRejectedValueOnce(new TypeError("Load failed"));
    const { replies, call } = await readingTracker(api);
    call("1", "storageWrite", { set: { a: "x" } });
    await waitFor(() => {
      expect(replies()).toHaveLength(1);
    });
    call("2", "storageWrite", { set: { a: "x" } });
    await waitFor(() => {
      expect(replies()).toHaveLength(2);
    });
    call("3", "storageWrite", { set: { a: "x" } });
    await waitFor(() => {
      expect(replies()).toEqual([
        refused("1", "quota", "Page data is limited to 2 MiB."),
        refused("2", "bad_request", "A key is 1 to 256 characters."),
        refused("3", "unavailable", "Nest could not store that."),
      ]);
    });
  });

  it("clears what the page stored when the page asks", async () => {
    const api = fakeApi();
    api.artifactStorage.mockResolvedValue({ items: { a: "1" }, size: 10 });
    api.clearArtifactStorage.mockResolvedValueOnce(null).mockRejectedValueOnce(new Error("down"));
    const { sheet, replies, call } = await readingTracker(api);
    await waitFor(() => {
      expect(meta(sheet)).toHaveTextContent("10 bytes stored");
    });
    call("1", "storageClear", {});
    await waitFor(() => {
      expect(replies()).toEqual([succeed("1", { size: 0 })]);
    });
    expect(meta(sheet)).not.toHaveTextContent("stored");
    call("2", "storageClear", {});
    await waitFor(() => {
      expect(replies()).toEqual([succeed("1", { size: 0 }), refused("2", "unavailable")]);
    });
  });

  it("brings the page in step with changes made elsewhere, but not with its own", async () => {
    const api = fakeApi();
    const { sheet, replies, call, changed } = await readingTracker(api);
    call("1", "storageWrite", { set: { b: "2", a: "1" }, remove: ["z", "y"] });
    await waitFor(() => {
      expect(replies()).toHaveLength(1);
    });
    // The echo of its own write, keys in any order.
    changed({ artifact_id: "t1", set: { a: "1", b: "2" }, remove: ["y", "z"], clear: false });
    // Another artifact's change.
    changed({ artifact_id: "other", set: { a: "9" }, remove: [], clear: false });
    expect(replies()).toHaveLength(1);
    expect(api.artifactStorage).toHaveBeenCalledTimes(1);

    // The same change again comes from elsewhere.
    api.artifactStorage.mockResolvedValue({ items: { a: "1" }, size: 1200 });
    changed({ artifact_id: "t1", set: { a: "1", b: "2" }, remove: ["y", "z"], clear: false });
    changed({ artifact_id: "t1", set: {}, remove: [], clear: true });
    expect(replies().slice(1)).toEqual([
      { nest: 1, event: "storage", key: "a", value: "1" },
      { nest: 1, event: "storage", key: "b", value: "2" },
      { nest: 1, event: "storage", key: "y", value: null },
      { nest: 1, event: "storage", key: "z", value: null },
      { nest: 1, event: "storage", clear: true },
    ]);
    await waitFor(() => {
      expect(meta(sheet)).toHaveTextContent("1.2 KB stored");
    });
  });

  it("passes on its own clear's echo to nobody, and forgets a refused write", async () => {
    const api = fakeApi();
    api.writeArtifactStorage.mockRejectedValueOnce(new Error("down"));
    const { replies, call, changed } = await readingTracker(api);
    call("1", "storageClear", {});
    call("2", "storageWrite", { set: { a: "1" } });
    await waitFor(() => {
      expect(replies()).toHaveLength(2);
    });
    changed({ artifact_id: "t1", set: {}, remove: [], clear: true });
    changed({ artifact_id: "t1", set: { a: "1" }, remove: [], clear: false });
    expect(replies().slice(2)).toEqual([{ nest: 1, event: "storage", key: "a", value: "1" }]);
  });

  it("stops passing changes on once the reader closes", async () => {
    const api = fakeApi();
    const { sheet, user, replies, changed } = await readingTracker(api);
    await user.click(within(sheet).getByRole("button", { name: "Artifacts" }));
    changed({ artifact_id: "t1", set: { a: "1" }, remove: [], clear: false });
    expect(replies()).toEqual([]);
  });

  describe("a file the page offers", () => {
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    /** Catches downloads: each blob and the name it was saved under. */
    function downloads() {
      const saved: { name: string; blob: Blob }[] = [];
      const blobs = new Map<string, Blob>();
      vi.stubGlobal(
        "URL",
        Object.assign(URL, {
          createObjectURL: (blob: Blob) => {
            const url = `blob:${String(blobs.size)}`;
            blobs.set(url, blob);
            return url;
          },
          revokeObjectURL: () => undefined,
        }),
      );
      vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
        this: HTMLAnchorElement,
      ) {
        const blob = blobs.get(this.getAttribute("href") ?? "");
        if (blob !== undefined) saved.push({ name: this.download, blob });
      });
      return saved;
    }

    it("is saved after the user says so, as plain bytes", async () => {
      const saved = downloads();
      const { user, replies, call } = await readingTracker();
      call("1", "saveFile", { name: "week.csv", content: "day,done\nmon,1\n", mime: "text/csv" });
      const ask = await screen.findByRole("alertdialog", { name: "Save “week.csv”?" });
      expect(ask).toHaveTextContent("15 bytes");
      expect(saved).toEqual([]);
      await user.click(within(ask).getByRole("button", { name: "Save" }));
      await waitFor(() => {
        expect(replies()).toEqual([succeed("1", { saved: true })]);
      });
      expect(saved.map((each) => each.name)).toEqual(["week.csv"]);
      expect(saved[0]?.blob.type).toBe("application/octet-stream");
      expect(await saved[0]?.blob.text()).toBe("day,done\nmon,1\n");
    });

    it("decodes a base64 file", async () => {
      const saved = downloads();
      const { user, replies, call } = await readingTracker();
      call("1", "saveFile", { name: "bytes.bin", content: "AP8Q", encoding: "base64" });
      const ask = await screen.findByRole("alertdialog", { name: "Save “bytes.bin”?" });
      expect(ask).toHaveTextContent("3 bytes");
      await user.click(within(ask).getByRole("button", { name: "Save" }));
      await waitFor(() => {
        expect(replies()).toHaveLength(1);
      });
      const bytes = new Uint8Array(await (saved[0]?.blob ?? new Blob()).arrayBuffer());
      expect([...bytes]).toEqual([0, 255, 16]);
    });

    it("answers declined on Cancel, and busy while another question is open", async () => {
      const saved = downloads();
      const { user, replies, call } = await readingTracker();
      call("1", "saveFile", { name: "a.txt", content: "a" });
      call("2", "openLink", { url: "https://example.com/" });
      await waitFor(() => {
        expect(replies()).toEqual([refused("2", "busy")]);
      });
      await user.click(
        within(await screen.findByRole("alertdialog", { name: "Save “a.txt”?" })).getByRole(
          "button",
          { name: "Cancel" },
        ),
      );
      await waitFor(() => {
        expect(replies()).toEqual([refused("2", "busy"), refused("1", "declined")]);
      });
      expect(saved).toEqual([]);
    });
  });
});

describe("the frame's colour scheme", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** The reader open on the plan, with the app's theme saved as given. */
  async function framedWith(theme: string) {
    const api = fakeApi();
    api.artifacts.mockResolvedValue([plan]);
    const storage = memoryStorage();
    storage.setItem(STORAGE_KEY, JSON.stringify({ theme }));
    const rendered = await openChat({ api, storage });
    await openHistory(rendered);
    await rendered.user.click(await screen.findByRole("button", { name: /^Rollout plan/ }));
    const sheet = await screen.findByRole("dialog", { name: "Options compared" });
    await showing(sheet, "# Options");
    return sheet;
  }

  it.each([
    ["dark", false, "dark"],
    ["light", true, "light"],
    ["auto", true, "dark"],
    ["auto", false, "light"],
  ])("is Nest's %s theme over a system that is dark: %s", async (theme, dark, scheme) => {
    systemDark(dark);
    const sheet = await framedWith(theme);
    expect(frameIn(sheet).style.colorScheme).toBe(scheme);
  });

  it("is light under Auto where the system cannot be asked", async () => {
    const sheet = await framedWith("auto");
    expect(frameIn(sheet).style.colorScheme).toBe("light");
  });

  it("follows the system under Auto, with a fresh page as it changes", async () => {
    const system = systemDark(false);
    const sheet = await framedWith("auto");
    const before = frameIn(sheet);
    system.flip(true);
    const after = frameIn(sheet);
    expect(after.style.colorScheme).toBe("dark");
    // A new document, since WebKit may not redo an open one's prefers-color-scheme.
    expect(after).not.toBe(before);
    expect(after.getAttribute("srcdoc")).toBe(before.getAttribute("srcdoc"));
  });
});
