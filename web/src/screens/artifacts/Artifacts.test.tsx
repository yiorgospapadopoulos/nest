import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { Artifact, JsonObject, NestEvent, Session } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import {
  artifact,
  artifactContent,
  detail,
  event,
  NOW,
  pixie,
  repo,
  session,
} from "../../test/fixtures.ts";
import { activityTime } from "../../format.ts";
import { openPixie } from "../../test/pixies.ts";
import { systemDark } from "../../test/motion.ts";
import { memoryStorage, renderApp } from "../../test/render.tsx";
import { STORAGE_KEY } from "../../appearance/appearance.ts";
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
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
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
    const listen = vi.spyOn(window, "addEventListener");
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
    expect(listen.mock.calls.some(([type]) => type === "message")).toBe(false);
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
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));
    expect(await screen.findByRole("heading", { name: "Pair this iPhone" })).toBeInTheDocument();
  });
});
