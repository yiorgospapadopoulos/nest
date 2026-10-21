import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { Artifact, ArtifactKind, JsonObject, NestEvent, Session } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import {
  artifact,
  artifactContent,
  artifactDetail,
  detail,
  event,
  NOW,
  pixie,
  repo,
  session,
  usagePeriod,
} from "../../test/fixtures.ts";
import { activityTime } from "../../format.ts";
import { openPixie } from "../../test/pixies.ts";
import { systemDark } from "../../test/motion.ts";
import { memoryStorage, renderApp } from "../../test/render.tsx";
import { STORAGE_KEY } from "../../appearance/appearance.ts";
import { PRINT, succeed } from "./bridge.ts";
import { ARTIFACT_CSP, withCsp } from "./html.ts";

const plan = artifact({
  id: "a1",
  title: "Rollout plan",
  latest_version: 3,
  version_count: 3,
  updated_at: "2026-10-06T09:00:00Z",
});
const report = artifact({
  id: "a2",
  title: "Usage report",
  kind: "html",
  seen: true,
  updated_at: "2026-10-06T09:30:00Z",
});

interface Setup {
  api?: FakeApi;
  chat?: Session;
  events?: NestEvent[];
  storage?: Storage;
}

/** The app with a chat open, and the API answering for artifacts. */
async function openChat({
  api = fakeApi(),
  chat = session(),
  events = [],
  storage = memoryStorage(),
}: Setup = {}) {
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.sessionEvents.mockResolvedValue(events);
  const rendered = await renderApp({ api, storage });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  const reconnect = async () => {
    const count = rendered.sockets.sockets.length;
    act(() => {
      rendered.sockets.last().drop(1006);
    });
    await waitFor(
      () => {
        expect(rendered.sockets.sockets).toHaveLength(count + 1);
      },
      { timeout: 3000 },
    );
    act(() => {
      rendered.sockets.last().open();
    });
  };
  return { ...rendered, reconnect };
}

/** The reader's sandboxed frame. */
function frameIn(sheet: HTMLElement): HTMLIFrameElement {
  const frame = sheet.querySelector("iframe");
  if (frame === null) throw new Error("no frame");
  return frame;
}

/** Waits until the reader's frame shows a page holding the text. */
async function showing(sheet: HTMLElement, text: string) {
  await waitFor(() => {
    expect(frameIn(sheet).getAttribute("srcdoc")).toContain(text);
  });
}

/** The history, opened from the chat's header. */
async function openHistory(rendered: Awaited<ReturnType<typeof openChat>>) {
  await rendered.user.click(screen.getByRole("button", { name: /^Artifacts/ }));
  return screen.findByRole("dialog", { name: "Artifacts" });
}

const rows = () =>
  within(screen.getByRole("list", { name: "Artifacts" }))
    .getAllByRole("button")
    .map((row) => row.textContent);

const saved = (found: Artifact, unseen: number): Partial<NestEvent> & { type: string } => ({
  id: 50,
  type: "artifact.saved",
  session_id: null,
  payload: {
    artifact: found as unknown as JsonObject,
    action: "updated",
    version: found.latest_version,
    unseen,
  },
});

const at = (iso: string) => activityTime(iso, new Date());

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the artifacts button (B79)", () => {
  it("shows how many are new in every project, live, and nothing at 0", async () => {
    const api = fakeApi();
    api.artifactsUnseen.mockResolvedValue({ unseen: 2 });
    const { push } = await openChat({ api });

    const button = await screen.findByRole("button", { name: "Artifacts, 2 new" });
    expect(button).toHaveTextContent("2");
    push({ type: "artifact.seen", payload: { artifact_id: "a1", unseen: 0 } });
    expect(screen.getByRole("button", { name: "Artifacts" })).toHaveTextContent("");
    push(saved(plan, 1));
    expect(screen.getByRole("button", { name: "Artifacts, 1 new" })).toBeInTheDocument();
  });

  it("reads the count and the lists again after a reconnect", async () => {
    const api = fakeApi();
    const rendered = await openChat({ api });
    await openHistory(rendered);
    await screen.findByText("No artifacts yet");
    // A stored event gives the socket a cursor, so the next connection resumes.
    rendered.push({
      id: 7,
      type: "repo.updated",
      session_id: null,
      payload: { repo: repo("cv-page") as unknown as JsonObject },
    });
    api.artifacts.mockResolvedValue([plan]);
    api.artifactsUnseen.mockResolvedValue({ unseen: 5 });
    await rendered.reconnect();

    expect(await screen.findByText("Rollout plan")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Artifacts, 5 new" })).toBeInTheDocument();
  }, 10_000);

  it("reads them again after a reconnect that cannot resume", async () => {
    const api = fakeApi();
    const rendered = await openChat({ api });
    await openHistory(rendered);
    await screen.findByText("No artifacts yet");
    api.artifacts.mockResolvedValue([report]);
    await rendered.reconnect();
    expect(await screen.findByText("Usage report")).toBeInTheDocument();
  }, 10_000);
});

describe("the artifact history", () => {
  it("lists the chat's first, newest first, with a switch to the project and every project", async () => {
    const api = fakeApi();
    api.artifacts.mockImplementation((filter) =>
      Promise.resolve(
        filter.session_id === "s1"
          ? [plan, report]
          : filter.repo === "cv-page"
            ? [
                plan,
                report,
                artifact({
                  id: "a3",
                  title: "Old notes",
                  chat_deleted: true,
                  updated_at: "2026-10-01T09:00:00Z",
                }),
              ]
            : [
                artifact({
                  id: "a4",
                  title: "Habit digest",
                  pixie_id: "p1",
                  pixie_name: "Tester",
                  repo: "pixie:p1",
                }),
                report,
              ],
      ),
    );
    const rendered = await openChat({ api });
    const sheet = await openHistory(rendered);

    expect(api.artifacts).toHaveBeenLastCalledWith({ session_id: "s1" });
    const choices = within(sheet).getByRole("group", { name: "Show artifacts of" });
    expect(within(choices).getByRole("button", { name: "This chat" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await within(sheet).findByText("Usage report");
    expect(rows()).toEqual([
      `Usage reportHTML · Validate contact form · ${at(report.updated_at)}`,
      `Rollout planMarkdown · Validate contact form · ${at(plan.updated_at)}`,
    ]);
    // Not opened yet: marked new.
    expect(screen.getAllByRole("img", { name: "New" })).toHaveLength(1);

    await rendered.user.click(within(choices).getByRole("button", { name: "This project" }));
    expect(api.artifacts).toHaveBeenLastCalledWith({ repo: "cv-page" });
    expect(await within(sheet).findByText("Old notes")).toBeInTheDocument();
    expect(rows()[2]).toBe(`Old notesMarkdown · Deleted chat · ${at("2026-10-01T09:00:00Z")}`);

    await rendered.user.click(within(choices).getByRole("button", { name: "All" }));
    expect(api.artifacts).toHaveBeenLastCalledWith({});
    await within(sheet).findByText("Habit digest");
    // Every project's names its project, except a pixie's, which names the pixie.
    expect(rows()).toEqual([
      `Habit digestMarkdown · Tester · ${at(NOW)}`,
      `Usage reportHTML · cv-page · Validate contact form · ${at(report.updated_at)}`,
    ]);
  });

  it("follows saves and deletions while it is open", async () => {
    const api = fakeApi();
    api.artifacts.mockResolvedValue([report]);
    const rendered = await openChat({ api });
    await openHistory(rendered);
    await screen.findByText("Usage report");

    rendered.push(saved({ ...plan, updated_at: "2026-10-06T09:45:00Z" }, 1));
    expect(rows()[0]).toMatch(/^Rollout plan/);
    // Another chat's is not this chat's.
    rendered.push(saved(artifact({ id: "a9", session_id: "s2", title: "Elsewhere" }), 1));
    expect(screen.queryByText("Elsewhere")).not.toBeInTheDocument();
    rendered.push({ type: "artifact.deleted", payload: { artifact_id: "a2", unseen: 1 } });
    expect(rows()).toHaveLength(1);
  });

  it("offers Retry when the list cannot be read", async () => {
    const api = fakeApi();
    api.artifacts.mockRejectedValueOnce(new ApiError(500, "boom"));
    const rendered = await openChat({ api });
    const sheet = await openHistory(rendered);
    expect(await within(sheet).findByText(/could not be loaded/)).toBeInTheDocument();
    api.artifacts.mockResolvedValue([plan]);
    await rendered.user.click(within(sheet).getByRole("button", { name: "Retry" }));
    expect(await within(sheet).findByText("Rollout plan")).toBeInTheDocument();
  });

  it("shows the list chosen last, whichever answers first, and closes", async () => {
    const api = fakeApi();
    let late: (artifacts: Artifact[]) => void = () => undefined;
    api.artifacts.mockImplementation((filter) =>
      filter.session_id === undefined
        ? Promise.resolve([report])
        : new Promise((resolve) => {
            late = resolve;
          }),
    );
    const rendered = await openChat({ api });
    const sheet = await openHistory(rendered);
    await rendered.user.click(within(sheet).getByRole("button", { name: "This project" }));
    await within(sheet).findByText("Usage report");
    act(() => {
      late([plan]);
    });
    await Promise.resolve();
    expect(within(sheet).queryByText("Rollout plan")).not.toBeInTheDocument();
    await rendered.user.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("is the pixie's from a pixie's page", async () => {
    const api = fakeApi();
    api.artifacts.mockResolvedValue([]);
    const shown = pixie({ id: "p1", name: "Tester" });
    const rendered = await openPixie(api, shown);
    await rendered.user.click(screen.getByRole("button", { name: "Artifacts" }));
    const sheet = await screen.findByRole("dialog", { name: "Artifacts" });
    expect(api.artifacts).toHaveBeenLastCalledWith({ pixie_id: "p1" });
    const choices = within(sheet).getByRole("group", { name: "Show artifacts of" });
    expect(
      within(choices)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["This pixie", "All"]);
  });
});

describe("the artifact reader", () => {
  async function reading(api = fakeApi()) {
    api.artifacts.mockResolvedValue([plan]);
    api.markArtifactSeen.mockResolvedValue({ ...plan, seen: true });
    api.artifactVersion.mockImplementation((id, version) =>
      Promise.resolve(
        artifactContent({
          artifact_id: id,
          version,
          title: version === 3 ? "Rollout plan" : "Draft plan",
          content: `# Plan ${String(version)}\n\nShip **it**.`,
          created_at: "2026-10-06T08:00:00Z",
        }),
      ),
    );
    const rendered = await openChat({ api });
    await openHistory(rendered);
    await rendered.user.click(await screen.findByRole("button", { name: /^Rollout plan/ }));
    const sheet = await screen.findByRole("dialog", { name: "Rollout plan" });
    await showing(sheet, "# Plan 3");
    return { ...rendered, sheet };
  }

  it("shows the latest version as Markdown and marks it seen", async () => {
    const api = fakeApi();
    const { sheet } = await reading(api);
    expect(api.artifactVersion).toHaveBeenCalledWith("a1", 3);
    // Rendered by the daemon's page in the sandboxed frame, not by the app.
    const frame = frameIn(sheet);
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("srcdoc")).toBe(
      withCsp(
        '<!doctype html><title>Rollout plan</title><pre id="nest-md"># Plan 3\n\nShip **it**.</pre>',
      ),
    );
    expect(within(sheet).queryByText("it")).not.toBeInTheDocument();
    expect(sheet).toHaveTextContent("Markdown");
    expect(sheet).toHaveTextContent("Validate contact form");
    expect(within(sheet).getByRole("group", { name: "Versions" })).toHaveTextContent(
      "Version 3 of 3",
    );
    await waitFor(() => {
      expect(api.markArtifactSeen).toHaveBeenCalledWith("a1");
    });
    expect(api.markArtifactSeen).toHaveBeenCalledTimes(1);
  });

  it("steps through the versions, each read once", async () => {
    const api = fakeApi();
    const { sheet, user } = await reading(api);
    const versions = within(sheet).getByRole("group", { name: "Versions" });
    expect(within(versions).getByRole("button", { name: "Next version" })).toBeDisabled();
    await user.click(within(versions).getByRole("button", { name: "Previous version" }));
    await showing(sheet, "# Plan 2");
    expect(versions).toHaveTextContent("Version 2 of 3");
    expect(screen.getByRole("dialog", { name: "Draft plan" })).toBe(sheet);
    await user.click(within(versions).getByRole("button", { name: "Previous version" }));
    await showing(sheet, "# Plan 1");
    expect(within(versions).getByRole("button", { name: "Previous version" })).toBeDisabled();
    await user.click(within(versions).getByRole("button", { name: "Next version" }));
    await showing(sheet, "# Plan 2");
    expect(api.artifactVersion.mock.calls.filter(([, v]) => v === 2)).toHaveLength(1);
  });

  it("copies the version's own text", async () => {
    const { sheet, user } = await reading();
    const write = vi.spyOn(navigator.clipboard, "writeText");
    await user.click(within(sheet).getByRole("button", { name: "Copy" }));
    expect(write).toHaveBeenCalledWith("# Plan 3\n\nShip **it**.");
    expect(await screen.findByText("Copied")).toBeInTheDocument();
    write.mockRejectedValue(new Error("not allowed"));
    await user.click(within(sheet).getByRole("button", { name: "Copy" }));
    expect(await screen.findByText("Could not copy")).toBeInTheDocument();
  });

  it("saves the version as a Markdown file named by its title", async () => {
    const { sheet, user } = await reading();
    const files: Blob[] = [];
    URL.createObjectURL = vi.fn((blob: Blob) => {
      files.push(blob);
      return "blob:plan";
    });
    URL.revokeObjectURL = vi.fn();
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    await user.click(within(sheet).getByRole("button", { name: "Save as file" }));
    expect(click).toHaveBeenCalledTimes(1);
    expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe("Rollout plan.md");
    expect(await files[0]?.text()).toBe("# Plan 3\n\nShip **it**.");
  });

  it("deletes it after asking, back to the history", async () => {
    const api = fakeApi();
    const { sheet, user } = await reading(api);
    await user.click(within(sheet).getByRole("button", { name: "Delete" }));
    const ask = screen.getByRole("alertdialog", { name: "Delete this artifact?" });
    // It opens on Cancel.
    await user.click(within(ask).getByRole("button", { name: "Cancel" }));
    expect(api.deleteArtifact).not.toHaveBeenCalled();
    api.artifacts.mockResolvedValue([]);
    await user.click(within(sheet).getByRole("button", { name: "Delete" }));
    await user.click(
      within(screen.getByRole("alertdialog", { name: "Delete this artifact?" })).getByRole(
        "button",
        {
          name: "Delete",
        },
      ),
    );
    expect(api.deleteArtifact).toHaveBeenCalledWith("a1");
    expect(await screen.findByRole("dialog", { name: "Artifacts" })).toBe(sheet);
    expect(await screen.findByText("Artifact deleted")).toBeInTheDocument();
    expect(within(sheet).getByText("No artifacts yet")).toBeInTheDocument();
  });

  it("goes back to the history, and leaves when it is deleted elsewhere", async () => {
    const { sheet, user, push } = await reading();
    await user.click(within(sheet).getByRole("button", { name: "Artifacts" }));
    expect(screen.getByRole("dialog", { name: "Artifacts" })).toBe(sheet);
    await user.click(within(sheet).getByRole("button", { name: /^Rollout plan/ }));
    await showing(sheet, "# Plan 3");
    push({ type: "artifact.deleted", payload: { artifact_id: "a1", unseen: 0 } });
    expect(screen.getByRole("dialog", { name: "Artifacts" })).toBe(sheet);
  });

  it("shows the version stepped to last, whichever answers first", async () => {
    const api = fakeApi();
    const { sheet, user } = await reading(api);
    let late: (content: ReturnType<typeof artifactContent>) => void = () => undefined;
    api.artifactVersion.mockReturnValueOnce(
      new Promise((resolve) => {
        late = resolve;
      }),
    );
    const versions = within(sheet).getByRole("group", { name: "Versions" });
    await user.click(within(versions).getByRole("button", { name: "Previous version" }));
    await user.click(within(versions).getByRole("button", { name: "Next version" }));
    await showing(sheet, "# Plan 3");
    act(() => {
      late(artifactContent({ version: 2, content: "# Plan 2" }));
    });
    await Promise.resolve();
    expect(frameIn(sheet).getAttribute("srcdoc")).toContain("# Plan 3");
  });

  it("offers Retry when a version cannot be read", async () => {
    const api = fakeApi();
    api.artifacts.mockResolvedValue([plan]);
    api.artifactVersion.mockRejectedValueOnce(new ApiError(500, "boom"));
    const rendered = await openChat({ api });
    await openHistory(rendered);
    await rendered.user.click(await screen.findByRole("button", { name: /^Rollout plan/ }));
    const sheet = await screen.findByRole("dialog", { name: "Rollout plan" });
    expect(await within(sheet).findByText(/could not be loaded/)).toBeInTheDocument();
    expect(within(sheet).queryByRole("button", { name: "Copy" })).not.toBeInTheDocument();
    await rendered.user.click(within(sheet).getByRole("button", { name: "Retry" }));
    await showing(sheet, "# Options");
  });
});

describe("an HTML artifact", () => {
  it("runs only in a sandboxed frame with the policy, never in the app", async () => {
    const api = fakeApi();
    const page =
      "<!doctype html><html><head><title>R</title></head><body><p id='evil'>Evil</p><script>parent.document.title='x'</script></body></html>";
    api.artifacts.mockResolvedValue([report]);
    api.artifactVersion.mockResolvedValue(
      artifactContent({ artifact_id: "a2", kind: "html", title: "Usage report", content: page }),
    );
    const rendered = await openChat({ api });
    await openHistory(rendered);
    await rendered.user.click(await screen.findByRole("button", { name: /^Usage report/ }));
    const sheet = await screen.findByRole("dialog", { name: "Usage report" });

    const frame = await within(sheet).findByTitle("Usage report");
    expect(frame.tagName).toBe("IFRAME");
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame).not.toHaveAttribute("src");
    expect(frame.getAttribute("srcdoc")).toBe(
      `<!doctype html><meta http-equiv="Content-Security-Policy" content="${ARTIFACT_CSP}">${page.slice(15)}`,
    );
    expect(document.getElementById("evil")).toBeNull();
    expect(screen.queryByText("Evil")).not.toBeInTheDocument();
    expect(sheet).toHaveTextContent("HTML");

    // Saved as written, without the policy.
    const files: Blob[] = [];
    URL.createObjectURL = vi.fn((blob: Blob) => {
      files.push(blob);
      return "blob:r";
    });
    URL.revokeObjectURL = vi.fn();
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    await rendered.user.click(within(sheet).getByRole("button", { name: "Save as file" }));
    expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe("Usage report.html");
    expect(await files[0]?.text()).toBe(page);
  });
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

describe("a page that reads usage and asks Claude (B88)", () => {
  const helper = artifact({ id: "h1", title: "Ask helper", kind: "html", seen: true });

  async function readingHelper(api = fakeApi()) {
    api.artifacts.mockResolvedValue([helper]);
    api.artifactVersion.mockImplementation((id, version) =>
      Promise.resolve(
        artifactContent({
          artifact_id: id,
          version,
          kind: "html",
          title: "Ask helper",
          content: "<p>Helper</p>",
        }),
      ),
    );
    const rendered = await openChat({ api });
    await openHistory(rendered);
    await rendered.user.click(await screen.findByRole("button", { name: /^Ask helper/ }));
    const sheet = await screen.findByRole("dialog", { name: "Ask helper" });
    await showing(sheet, "Helper");
    const page = frameIn(sheet).contentWindow;
    if (page === null) throw new Error("no window");
    const sent = vi.spyOn(page, "postMessage");
    const replies = () => sent.mock.calls.map(([reply]) => reply as unknown);
    const call = (id: string, method: string, params: unknown) => {
      act(() => {
        window.dispatchEvent(
          new MessageEvent("message", { data: { nest: 1, id, method, params }, source: page }),
        );
      });
    };
    const asked = (payload: JsonObject) => {
      rendered.push({ id: null, type: "artifact.ask", payload });
    };
    return { ...rendered, api, sheet, replies, call, asked };
  }

  const refused = (id: string, code: string, message: string = expect.any(String) as string) => ({
    nest: 1,
    id,
    ok: false,
    error: { code, message },
  });
  const usage = {
    limits: { five_hour: { utilization: 0.3, resets_at: null }, seven_day: null },
    today: { tokens: usagePeriod().tokens.total, sessions: usagePeriod().sessions },
    week: { tokens: usagePeriod().tokens.total, sessions: usagePeriod().sessions },
  };

  it("answers usage with the Usage page's numbers", async () => {
    const { replies, call } = await readingHelper();
    call("1", "usage", {});
    await waitFor(() => {
      expect(replies()).toEqual([succeed("1", usage)]);
    });
  });

  it("answers unavailable when usage cannot be read", async () => {
    const api = fakeApi();
    api.usageLimits.mockRejectedValue(new Error("offline"));
    const { replies, call } = await readingHelper(api);
    call("1", "usage", {});
    await waitFor(() => {
      expect(replies()).toEqual([refused("1", "unavailable")]);
    });
  });

  it("sends fresh usage when it changes, only to a page that read it", async () => {
    const api = fakeApi();
    const { replies, call, push } = await readingHelper(api);
    push({ id: null, type: "usage.updated", payload: {} });
    await act(() => Promise.resolve());
    expect(replies()).toEqual([]);
    call("1", "usage", {});
    await waitFor(() => {
      expect(replies()).toHaveLength(1);
    });
    const reads = api.usageLimits.mock.calls.length;
    push({ id: null, type: "usage.updated", payload: {} });
    await waitFor(() => {
      expect(replies()).toEqual([succeed("1", usage), { nest: 1, event: "usage", usage }]);
    });
    expect(api.usageLimits.mock.calls.length).toBe(reads + 1);
  });

  it("drops a usage change it cannot read", async () => {
    const api = fakeApi();
    const { replies, call, push } = await readingHelper(api);
    call("1", "usage", {});
    await waitFor(() => {
      expect(replies()).toHaveLength(1);
    });
    api.usageLimits.mockRejectedValueOnce(new Error("offline"));
    push({ id: null, type: "usage.updated", payload: {} });
    await act(() => Promise.resolve());
    await act(() => Promise.resolve());
    expect(replies()).toHaveLength(1);
  });

  it("asks Claude, showing that it does, then today's count", async () => {
    const api = fakeApi();
    let answer: () => void = () => undefined;
    api.askArtifact.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          answer = () => {
            resolve({ text: "Autumn light", remaining: 19 });
          };
        }),
    );
    const { sheet, replies, call } = await readingHelper(api);
    expect(within(sheet).queryByRole("status")).toBeNull();
    call("1", "ask", { prompt: "A haiku", system: "Brief" });
    expect(await within(sheet).findByRole("status")).toHaveTextContent("Asking Claude...");
    expect(api.askArtifact).toHaveBeenCalledWith("h1", { prompt: "A haiku", system: "Brief" });
    act(() => {
      answer();
    });
    await waitFor(() => {
      expect(replies()).toEqual([succeed("1", { text: "Autumn light", remaining: 19 })]);
    });
    expect(within(sheet).queryByRole("status")).toBeNull();
    expect(sheet.querySelector(".afmeta")).toHaveTextContent("1 of 20 asks today");
  });

  it("takes the daily limit from the Mac when it says it", async () => {
    const api = fakeApi();
    api.askArtifact.mockResolvedValueOnce({ text: "Hi", remaining: 3, limit: 5 });
    const { sheet, call } = await readingHelper(api);
    call("1", "ask", { prompt: "Hi" });
    await waitFor(() => {
      expect(sheet.querySelector(".afmeta")).toHaveTextContent("2 of 5 asks today");
    });
  });

  it("maps the Mac's refusals to the page's error codes", async () => {
    const api = fakeApi();
    api.askArtifact
      .mockRejectedValueOnce(
        new ApiError(429, "Daily limit reached", null, { resets_at: "2026-10-20T00:00:00" }),
      )
      .mockRejectedValueOnce(new ApiError(403, "Asking is off"))
      .mockRejectedValueOnce(new ApiError(409, "Already asking"))
      .mockRejectedValueOnce(new ApiError(500, "Claude failed"))
      .mockRejectedValueOnce(new TypeError("Load failed"))
      .mockRejectedValueOnce(new ApiError(429, "Daily limit reached"));
    const { sheet, replies, call } = await readingHelper(api);
    for (const id of ["1", "2", "3", "4", "5", "6"]) {
      call(id, "ask", { prompt: "Hi" });
      await waitFor(() => {
        expect(replies()).toHaveLength(Number(id));
      });
    }
    const resets = new Date("2026-10-20T00:00:00").toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
    });
    expect(replies()).toEqual([
      refused("1", "budget", expect.stringContaining(resets) as string),
      refused("2", "disabled", "Asking is off"),
      refused("3", "busy", "Already asking"),
      refused("4", "unavailable", "Claude failed"),
      refused("5", "unavailable", "Claude could not answer."),
      refused("6", "budget", expect.stringContaining("Reset time unknown") as string),
    ]);
    expect((replies()[0] as { error: { message: string } }).error.message).toMatch(
      /^Today's asks for this page are used up\. Resets /,
    );
    expect(within(sheet).queryByRole("status")).toBeNull();
    expect(sheet.querySelector(".afmeta")).not.toHaveTextContent("asks today");
  });

  it("shows today's count on opening once the page has asked", async () => {
    const api = fakeApi();
    api.askStatus.mockResolvedValue({
      used: 4,
      limit: 30,
      remaining: 26,
      resets_at: null,
      enabled: true,
    });
    const { sheet } = await readingHelper(api);
    expect(api.askStatus).toHaveBeenCalledWith("h1");
    await waitFor(() => {
      expect(sheet.querySelector(".afmeta")).toHaveTextContent("4 of 30 asks today");
    });
  });

  it("shows no count on opening before any ask, or when it cannot be read", async () => {
    const api = fakeApi();
    api.askStatus.mockRejectedValueOnce(new Error("offline"));
    const { sheet } = await readingHelper(api);
    await act(() => Promise.resolve());
    expect(sheet.querySelector(".afmeta")).not.toHaveTextContent("asks today");
    await waitFor(() => {
      expect(api.askStatus).toHaveBeenCalledTimes(1);
    });
  });

  it("shows another device's ask from the Mac's events", async () => {
    const { sheet, asked } = await readingHelper();
    asked({ artifact_id: "other", state: "started", remaining: 4 });
    expect(within(sheet).queryByRole("status")).toBeNull();
    asked({ artifact_id: "h1", state: "started", remaining: 18 });
    expect(within(sheet).getByRole("status")).toHaveTextContent("Asking Claude...");
    expect(sheet.querySelector(".afmeta")).not.toHaveTextContent("asks today");
    asked({ artifact_id: "h1", state: "finished", remaining: 17 });
    expect(within(sheet).queryByRole("status")).toBeNull();
    expect(sheet.querySelector(".afmeta")).toHaveTextContent("3 of 20 asks today");
    asked({ artifact_id: "h1", state: "finished", remaining: 9, limit: 10 });
    expect(sheet.querySelector(".afmeta")).toHaveTextContent("1 of 10 asks today");
    // A finish that does not say what is left keeps the count.
    asked({ artifact_id: "h1", state: "finished" });
    expect(sheet.querySelector(".afmeta")).toHaveTextContent("1 of 10 asks today");
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

describe("an artifact card in the transcript", () => {
  const card = (id: number, payload: JsonObject) =>
    event({ id, type: "session.artifact", payload });

  it("opens the version it names, and the history from there", async () => {
    const api = fakeApi();
    api.artifact.mockResolvedValue({ ...plan, versions: [] });
    api.artifacts.mockResolvedValue([plan]);
    const rendered = await openChat({
      api,
      events: [
        card(1, {
          artifact_id: "a1",
          version: 1,
          title: "Draft plan",
          kind: "markdown",
          action: "created",
        }),
        card(2, {
          artifact_id: "a1",
          version: 2,
          title: "Rollout plan",
          kind: "markdown",
          action: "updated",
        }),
      ],
    });
    const first = await screen.findByRole("group", { name: "Artifact: Draft plan" });
    expect(first).toHaveTextContent("Saved · Markdown");
    const second = screen.getByRole("group", { name: "Artifact: Rollout plan" });
    expect(second).toHaveTextContent("Version 2 · Markdown");
    // Both name the same artifact, looked up once.
    expect(api.artifact).toHaveBeenCalledTimes(1);

    await rendered.user.click(within(first).getByRole("button", { name: "Open" }));
    const sheet = await screen.findByRole("dialog", { name: "Options compared" });
    expect(api.artifactVersion).toHaveBeenCalledWith("a1", 1);
    expect(within(sheet).getByRole("group", { name: "Versions" })).toHaveTextContent(
      "Version 1 of 3",
    );
    // An older version is not the one to mark seen.
    expect(api.markArtifactSeen).not.toHaveBeenCalled();
    await rendered.user.click(within(sheet).getByRole("button", { name: "Artifacts" }));
    expect(await within(sheet).findByText("Rollout plan")).toBeInTheDocument();
    await rendered.user.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens before the artifact is known, waiting for it", async () => {
    const api = fakeApi();
    let found: (value: typeof plan & { versions: [] }) => void = () => undefined;
    api.artifact.mockReturnValue(
      new Promise((resolve) => {
        found = resolve;
      }),
    );
    const rendered = await openChat({
      api,
      events: [
        card(1, {
          artifact_id: "a1",
          version: 3,
          title: "Rollout plan",
          kind: "markdown",
          action: "updated",
        }),
      ],
    });
    const shown = await screen.findByRole("group", { name: "Artifact: Rollout plan" });
    await rendered.user.click(within(shown).getByRole("button", { name: "Open" }));
    const sheet = await screen.findByRole("dialog", { name: "Options compared" });
    expect(sheet).toHaveTextContent("Loading...");
    act(() => {
      found({ ...plan, versions: [] });
    });
    expect(await within(sheet).findByText("Version 3 of 3")).toBeInTheDocument();
    await waitFor(() => {
      expect(api.markArtifactSeen).toHaveBeenCalledWith("a1");
    });
  });

  it("shows one deleted as Deleted, with nothing to open", async () => {
    const api = fakeApi();
    api.artifact.mockImplementation((id) =>
      id === "gone"
        ? Promise.reject(new ApiError(404, "Not found"))
        : Promise.resolve({ ...plan, versions: [] }),
    );
    const rendered = await openChat({
      api,
      events: [
        card(1, { artifact_id: "gone", version: 1, title: "Old", kind: "html", action: "created" }),
        card(2, {
          artifact_id: "a1",
          version: 1,
          title: "Live",
          kind: "markdown",
          action: "created",
        }),
      ],
    });
    const old = await screen.findByRole("group", { name: "Artifact: Old" });
    await waitFor(() => {
      expect(old).toHaveTextContent("Deleted · HTML");
    });
    expect(within(old).getByRole("button", { name: "Open" })).toBeDisabled();

    const live = screen.getByRole("group", { name: "Artifact: Live" });
    await rendered.user.click(within(live).getByRole("button", { name: "Open" }));
    await screen.findByRole("dialog", { name: "Options compared" });
    rendered.push({ type: "artifact.deleted", payload: { artifact_id: "a1", unseen: 0 } });
    expect(live).toHaveTextContent("Deleted · Markdown");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the card when the lookup fails for another reason", async () => {
    const api = fakeApi();
    api.artifact.mockRejectedValue(new ApiError(500, "boom"));
    await openChat({
      api,
      events: [
        card(1, {
          artifact_id: "a1",
          version: 1,
          title: "Plan",
          kind: "markdown",
          action: "created",
        }),
      ],
    });
    const shown = await screen.findByRole("group", { name: "Artifact: Plan" });
    await waitFor(() => {
      expect(api.artifact).toHaveBeenCalled();
    });
    expect(within(shown).getByRole("button", { name: "Open" })).toBeEnabled();
  });

  it("sends the app back to pairing when the device is no longer paired", async () => {
    const api = fakeApi();
    api.artifact.mockRejectedValue(new ApiError(401, "Unauthorized"));
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [session()]));
    api.sessionEvents.mockResolvedValue([
      card(1, {
        artifact_id: "a1",
        version: 1,
        title: "Plan",
        kind: "markdown",
        action: "created",
      }),
    ]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));
    expect(await screen.findByRole("heading", { name: "Pair this iPhone" })).toBeInTheDocument();
  });
});
