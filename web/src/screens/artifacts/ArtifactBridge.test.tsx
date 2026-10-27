import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { ArtifactKind } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { artifact, artifactContent, artifactDetail, NOW } from "../../test/fixtures.ts";
import { PRINT, succeed } from "./bridge.ts";
import { frameIn, openChat, openHistory, plan, showing } from "../../test/artifacts.ts";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the page bridge (B88)", () => {
  /** The reader open on the plan's latest version, with what its frame is sent. */
  async function bridged() {
    const api = fakeApi();
    api.artifacts.mockResolvedValue([plan]);
    const rendered = await openChat({ api });
    await openHistory(rendered);
    await rendered.user.click(await screen.findByRole("button", { name: /^Rollout plan/ }));
    const sheet = await screen.findByRole("dialog", { name: "Options compared" });
    await showing(sheet, "# Options");
    const spy = () => {
      const page = frameIn(sheet).contentWindow;
      if (page === null) throw new Error("no window");
      return vi.spyOn(page, "postMessage");
    };
    let sent = spy();
    const replies = () => sent.mock.calls.map(([reply]) => reply as unknown);
    // Watches the frame shown now, from its first reply.
    const watch = () => {
      sent = spy();
    };
    /** A message as the page in the frame (or another source) posts it to the app. */
    const post = (
      data: unknown,
      source: MessageEventSource | null = frameIn(sheet).contentWindow,
    ) => {
      act(() => {
        window.dispatchEvent(new MessageEvent("message", { data, source }));
      });
    };
    const open = (id: string, url: unknown) => {
      post({ nest: 1, id, method: "openLink", params: { url } });
    };
    return { ...rendered, api, sheet, replies, watch, post, open };
  }

  const refused = (id: string, code: string) => ({
    nest: 1,
    id,
    ok: false,
    error: { code, message: expect.any(String) as string },
  });

  /** Waits for the frame to have been answered with exactly these replies. */
  async function answered(replies: () => unknown[], expected: unknown[]) {
    await waitFor(() => {
      expect(replies()).toEqual(expected);
    });
  }

  it("asks before opening a link, then opens it in a new tab and says so", async () => {
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    const { user, replies, open } = await bridged();
    open("1-a", "https://example.com/docs");

    const ask = await screen.findByRole("alertdialog", { name: "Open link?" });
    expect(ask).toHaveTextContent("https://example.com/docs");
    const action = within(ask).getByRole("button", { name: "Open" });
    // Opening a link is not a danger.
    expect(action).not.toHaveClass("dng");
    // It opens on Cancel, as every confirmation does.
    expect(within(ask).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(replies()).toEqual([]);

    await user.click(action);
    expect(opened).toHaveBeenCalledWith(
      "https://example.com/docs",
      "_blank",
      "noopener,noreferrer",
    );
    await answered(replies, [{ nest: 1, id: "1-a", ok: true, result: { opened: true } }]);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    // A later Cancel cannot follow an Open: the page keeps its first answer.
    await act(() => Promise.resolve());
    expect(replies()).toHaveLength(1);
  });

  it("puts a long link's host first, and opens a mail link", async () => {
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    const { user, replies, open } = await bridged();
    const long = `https://docs.example.com/guide/${"a".repeat(60)}`;
    open("1", long);
    const ask = await screen.findByRole("alertdialog", { name: "Open link?" });
    expect(ask.querySelector(".ast")?.textContent).toBe(`Open link?docs.example.com\n${long}`);
    await user.click(within(ask).getByRole("button", { name: "Cancel" }));
    open("2", "mailto:me@example.com");
    await user.click(
      within(await screen.findByRole("alertdialog", { name: "Open link?" })).getByRole("button", {
        name: "Open",
      }),
    );
    expect(opened).toHaveBeenCalledWith("mailto:me@example.com", "_blank", "noopener,noreferrer");
    await answered(replies, [refused("1", "declined"), succeed("2", { opened: true })]);
  });

  it("declines when the user cancels, and asks again for the next link", async () => {
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    const { user, replies, open } = await bridged();
    open("1", "https://example.com/");
    await user.click(
      within(await screen.findByRole("alertdialog", { name: "Open link?" })).getByRole("button", {
        name: "Cancel",
      }),
    );
    await answered(replies, [refused("1", "declined")]);
    expect(opened).not.toHaveBeenCalled();

    open("2", "https://example.com/next");
    const ask = await screen.findByRole("alertdialog", { name: "Open link?" });
    expect(ask).toHaveTextContent("https://example.com/next");
    await user.keyboard("{Escape}");
    await answered(replies, [refused("1", "declined"), refused("2", "declined")]);
  });

  it("answers busy to a second link while it is asking about one", async () => {
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    const { user, replies, open } = await bridged();
    open("1", "https://example.com/one");
    open("2", "https://example.com/two");
    await answered(replies, [refused("2", "busy")]);
    const ask = screen.getByRole("alertdialog", { name: "Open link?" });
    expect(ask).toHaveTextContent("https://example.com/one");
    await user.click(within(ask).getByRole("button", { name: "Open" }));
    await answered(replies, [refused("2", "busy"), succeed("1", { opened: true })]);
    expect(opened).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["javascript:", "javascript:alert(1)"],
    ["data:", "data:text/html,<script>alert(1)</script>"],
    ["a relative link", "/elsewhere"],
    ["a non-string", 7],
  ])("refuses %s without asking", async (_, url) => {
    const { replies, open } = await bridged();
    open("1", url);
    await answered(replies, [refused("1", "bad_request")]);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("ignores messages from anything but its own frame", async () => {
    const { sheet, replies, post } = await bridged();
    const request = { nest: 1, id: "1", method: "openLink", params: { url: "https://e.com" } };
    post(request, window);
    post(request, null);
    const other = document.createElement("iframe");
    document.body.append(other);
    post(request, other.contentWindow);
    other.remove();
    await act(() => Promise.resolve());
    expect(replies()).toEqual([]);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(frameIn(sheet)).toBeInTheDocument();
  });

  it("answers malformed, oversized and unknown requests, and ignores those without an id", async () => {
    const { replies, post } = await bridged();
    post({ nest: 1, method: "openLink", params: {} });
    post("hello");
    post({ nest: 1, id: "1", method: "openLink" });
    post({
      nest: 1,
      id: "2",
      method: "openLink",
      params: { url: "https://e.com", pad: "a".repeat(70_000) },
    });
    post({ nest: 1, id: "3", method: "readFile", params: {} });
    await answered(replies, [
      refused("1", "bad_request"),
      refused("2", "too_large"),
      refused("3", "unknown_method"),
    ]);
  });

  it("answers rate_limited past 30 requests in 10 s, and a new page starts fresh", async () => {
    let time = 1_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => time);
    const { user, sheet, replies, post, watch } = await bridged();
    for (let i = 0; i < 31; i++) post({ nest: 1, id: String(i), method: "nope", params: {} });
    await waitFor(() => {
      expect(replies()).toHaveLength(31);
    });
    expect(replies().slice(0, 30)).toEqual(
      Array.from({ length: 30 }, (_, i) => refused(String(i), "unknown_method")),
    );
    expect(replies()[30]).toEqual(refused("30", "rate_limited"));

    time += 10_000;
    post({ nest: 1, id: "later", method: "nope", params: {} });
    await waitFor(() => {
      expect(replies().at(-1)).toEqual(refused("later", "unknown_method"));
    });

    // Another version is another page, with a window of its own.
    for (let i = 0; i < 30; i++) post({ nest: 1, id: `x${String(i)}`, method: "nope", params: {} });
    post({ nest: 1, id: "full", method: "nope", params: {} });
    await waitFor(() => {
      expect(replies().at(-1)).toEqual(refused("full", "rate_limited"));
    });
    const before = frameIn(sheet);
    await user.click(within(sheet).getByRole("button", { name: "Previous version" }));
    await showing(sheet, "# Options");
    expect(frameIn(sheet)).not.toBe(before);
    watch();
    post({ nest: 1, id: "fresh", method: "nope", params: {} });
    await answered(replies, [refused("fresh", "unknown_method")]);
  });

  it("dismisses its question when the version changes, without an answer", async () => {
    const { user, sheet, replies, open } = await bridged();
    open("1", "https://example.com/");
    await screen.findByRole("alertdialog", { name: "Open link?" });
    await user.click(within(sheet).getByRole("button", { name: "Previous version" }));
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });
    await act(() => Promise.resolve());
    expect(replies()).toEqual([]);
  });

  it("stops listening and dismisses its question when the reader closes", async () => {
    const { user, sheet, replies, open, post } = await bridged();
    const listening = vi.spyOn(window, "removeEventListener");
    open("1", "https://example.com/");
    await screen.findByRole("alertdialog", { name: "Open link?" });
    const frameWindow = frameIn(sheet).contentWindow;
    await user.click(within(sheet).getByRole("button", { name: "Artifacts" }));
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });
    expect(listening.mock.calls.some(([type]) => type === "message")).toBe(true);
    post({ nest: 1, id: "2", method: "nope", params: {} }, frameWindow);
    await act(() => Promise.resolve());
    expect(replies()).toEqual([]);
  });
});

describe("the ready-made kinds (B88)", () => {
  const guide = artifact({
    id: "g1",
    title: "Team guide",
    kind: "document",
    latest_version: 3,
    version_count: 3,
    seen: true,
  });

  /** The reader open on the latest version of an artifact of `kind`, and its frame's mail. */
  async function readingKind(kind: ArtifactKind, api = fakeApi()) {
    const found = { ...guide, kind };
    api.artifacts.mockResolvedValue([found]);
    api.artifact.mockResolvedValue(artifactDetail({ ...found, latest_version: 4 }));
    api.artifactVersion.mockImplementation((id, version) =>
      Promise.resolve(
        artifactContent({
          artifact_id: id,
          version,
          kind,
          title: "Team guide",
          content: `# Guide ${String(version)}`,
          author: version === 4 ? "user" : "agent",
        }),
      ),
    );
    const rendered = await openChat({ api });
    await openHistory(rendered);
    await rendered.user.click(await screen.findByRole("button", { name: /^Team guide/ }));
    const sheet = await screen.findByRole("dialog", { name: "Team guide" });
    await showing(sheet, "# Guide 3");
    const page = frameIn(sheet).contentWindow;
    if (page === null) throw new Error("no window");
    const sent = vi.spyOn(page, "postMessage");
    const replies = () => sent.mock.calls.map(([reply]) => reply as unknown);
    const post = (data: unknown) => {
      act(() => {
        window.dispatchEvent(new MessageEvent("message", { data, source: page }));
      });
    };
    const save = (id: string, content: string, base_version: unknown = 3) => {
      post({ nest: 1, id, method: "saveDocument", params: { content, base_version } });
    };
    return { ...rendered, api, sheet, sent, replies, post, save };
  }

  const refused = (id: string, code: string, message: string = expect.any(String) as string) => ({
    nest: 1,
    id,
    ok: false,
    error: { code, message },
  });

  it.each([
    ["slides", "Slides", "allow-scripts allow-modals", true],
    ["document", "Document", "allow-scripts allow-modals", true],
    ["design", "Design", "allow-scripts", false],
    ["design_system", "Design system", "allow-scripts", false],
    ["markdown", "Markdown", "allow-scripts", false],
    ["html", "HTML", "allow-scripts", false],
  ] as const)("shows %s as %s, sandboxed %j, printable: %s", async (kind, label, sandbox, pdf) => {
    const { sheet } = await readingKind(kind);
    expect(sheet.querySelector(".afk")).toHaveTextContent(label);
    expect(frameIn(sheet).getAttribute("sandbox")).toBe(sandbox);
    expect(within(sheet).queryByRole("button", { name: "Export PDF" }) !== null).toBe(pdf);
  });

  it("asks the page to print itself on Export PDF", async () => {
    const { sheet, sent, user } = await readingKind("slides");
    await user.click(within(sheet).getByRole("button", { name: "Export PDF" }));
    expect(sent).toHaveBeenCalledWith(PRINT, "*");
    expect(sent).toHaveBeenCalledTimes(1);
  });

  it("saves an edited document as its next version, answers, then shows it", async () => {
    const api = fakeApi();
    const { sheet, replies, save } = await readingKind("document", api);
    // The agent's version says nothing of who saved it.
    expect(within(sheet).getByRole("group", { name: "Versions" })).not.toHaveTextContent(
      "Edited by you",
    );
    save("1", "# Guide, edited");
    await waitFor(() => {
      expect(replies()).toEqual([succeed("1", { version: 4 })]);
    });
    expect(api.saveArtifactVersion).toHaveBeenCalledWith("g1", {
      content: "# Guide, edited",
      base_version: 3,
    });
    await showing(sheet, "# Guide 4");
    const versions = within(sheet).getByRole("group", { name: "Versions" });
    await waitFor(() => {
      expect(versions).toHaveTextContent("Version 4 of 4");
    });
    expect(versions).toHaveTextContent("Edited by you");
    expect(api.artifactVersion).toHaveBeenCalledWith("g1", 4);
  });

  it("answers conflict when the document changed since its version", async () => {
    const api = fakeApi();
    api.saveArtifactVersion.mockRejectedValueOnce(new ApiError(409, "Version 3 is not the latest"));
    const { sheet, replies, save } = await readingKind("document", api);
    save("1", "# Mine");
    await waitFor(() => {
      expect(replies()).toEqual([refused("1", "conflict")]);
    });
    expect(within(sheet).getByRole("group", { name: "Versions" })).toHaveTextContent(
      "Version 3 of 3",
    );
  });

  it("answers unavailable with the Mac's reason, or a plain one offline", async () => {
    const api = fakeApi();
    api.saveArtifactVersion
      .mockRejectedValueOnce(new ApiError(422, "The document is empty."))
      .mockRejectedValueOnce(new TypeError("Load failed"));
    const { replies, save } = await readingKind("document", api);
    save("1", "");
    await waitFor(() => {
      expect(replies()).toHaveLength(1);
    });
    save("2", "# Again");
    await waitFor(() => {
      expect(replies()).toEqual([
        refused("1", "unavailable", "The document is empty."),
        refused("2", "unavailable", "Nest could not save the document."),
      ]);
    });
  });

  it("answers busy to a second save while one is on its way", async () => {
    const api = fakeApi();
    let finish: () => void = () => undefined;
    api.saveArtifactVersion.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = () => {
            resolve({ version: 4, title: "Team guide", size: 1, created_at: NOW, author: "user" });
          };
        }),
    );
    const { replies, save } = await readingKind("document", api);
    save("1", "# One");
    save("2", "# Two");
    await waitFor(() => {
      expect(replies()).toEqual([refused("2", "busy")]);
    });
    finish();
    await waitFor(() => {
      expect(replies()).toEqual([refused("2", "busy"), succeed("1", { version: 4 })]);
    });
    expect(api.saveArtifactVersion).toHaveBeenCalledTimes(1);
  });

  it.each(["slides", "markdown", "html", "design"] as const)(
    "refuses a save from a %s page",
    async (kind) => {
      const api = fakeApi();
      const { replies, save } = await readingKind(kind, api);
      save("1", "# Mine");
      await waitFor(() => {
        expect(replies()).toEqual([refused("1", "bad_request")]);
      });
      expect(api.saveArtifactVersion).not.toHaveBeenCalled();
    },
  );

  it("refuses a save from an older version of a document", async () => {
    const api = fakeApi();
    const { sheet, user } = await readingKind("document", api);
    await user.click(within(sheet).getByRole("button", { name: "Previous version" }));
    await showing(sheet, "# Guide 2");
    const page = frameIn(sheet).contentWindow;
    if (page === null) throw new Error("no window");
    const sent = vi.spyOn(page, "postMessage");
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: {
            nest: 1,
            id: "1",
            method: "saveDocument",
            params: { content: "# Old", base_version: 2 },
          },
          source: page,
        }),
      );
    });
    await waitFor(() => {
      expect(sent).toHaveBeenCalledWith(refused("1", "bad_request"), "*");
    });
    expect(api.saveArtifactVersion).not.toHaveBeenCalled();
  });

  it("refuses a save whose params do not check, before asking the Mac", async () => {
    const api = fakeApi();
    const { replies, save } = await readingKind("document", api);
    save("1", "# Mine", "3");
    await waitFor(() => {
      expect(replies()).toEqual([refused("1", "bad_request")]);
    });
    expect(api.saveArtifactVersion).not.toHaveBeenCalled();
  });
});
