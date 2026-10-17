import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { AgentWork, CallWork, GroupEntry, JsonValue } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import {
  callEntry,
  callWork,
  detail,
  groupEntry,
  pixie,
  repo,
  session,
  team,
  trackedAgent,
} from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const SCRIBE = pixie({ id: "scribe", slug: "scribe", name: "Scribe" });
const LEAD = pixie({ id: "lead", slug: "lead", name: "Lead", team_id: "qa" });
const BUGS = pixie({ id: "bugs", slug: "bugs", name: "Bugs", team_id: "qa", position: 1 });
const QA = team({ id: "qa", name: "QA crew", handle: "qa", leader_id: "lead" });

const read = (id: string, path: string): JsonValue => ({
  type: "tool_use",
  id,
  name: "Read",
  input: { file_path: `/w/s1/${path}` },
});
const result = (id: string, content: string): JsonValue => ({
  type: "tool_result",
  tool_use_id: id,
  content,
  is_error: false,
});
const text = (value: string): JsonValue => ({ type: "text", text: value });

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function setup(groups: Record<string, GroupEntry[]> = {}): FakeApi {
  const chat = session({ state: "running" });
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.pixies.mockResolvedValue([SCRIBE, LEAD, BUGS]);
  api.teams.mockResolvedValue([QA]);
  api.pixieGroups.mockResolvedValue(groups);
  api.session.mockResolvedValue(
    detail({ ...chat, agents: [trackedAgent({ id: "x1", description: "Find the form" })] }),
  );
  return api;
}

async function openList(api: FakeApi) {
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  await screen.findByRole("list", { name: "Working in Validate contact form" });
  return rendered;
}

describe("a subagent's transcript (B46)", () => {
  it("shows what it was asked, its tool calls and results, live, then its report", async () => {
    const api = setup();
    api.agentTranscript.mockResolvedValueOnce({
      tool_use_id: "x1",
      prompt: "Find the **contact form**",
      messages: [
        { event_id: 5, ts: "x", blocks: [read("r1", "app/form.tsx")] },
        { event_id: 6, ts: "x", blocks: [result("r1", "export function Form() {}")] },
      ],
      report: null,
    });
    const { user, push } = await openList(api);

    await user.click(screen.getByRole("button", { name: "Explore, Find the form, working" }));
    const page = await screen.findByRole("region", { name: "Explore" });
    expect(api.agentTranscript).toHaveBeenCalledWith("s1", "x1");
    expect(within(page).getByText("Find the form")).toBeInTheDocument();
    await within(page).findByText("app/form.tsx");
    expect(within(page).getByText("contact form").tagName).toBe("STRONG");
    expect(within(page).getByText("Working").querySelector(".ff")).not.toBeNull();
    // The header's status after the name is the fireflies while it works (B80).
    expect(within(page).getByRole("img", { name: "Working" })).toHaveClass("ff");
    expect(within(page).getByText("Read only. Ask follow-ups in the chat.")).toBeInTheDocument();
    expect(within(page).queryByLabelText("Message")).not.toBeInTheDocument();

    // A message of this subagent arrives; others' and older ones do not show again.
    push({
      id: 7,
      type: "session.message",
      session_id: "s1",
      payload: { parent_tool_use_id: "x1", blocks: [text("Found it in app/form.tsx")] },
    });
    push({
      id: 8,
      type: "session.message",
      session_id: "s1",
      payload: { parent_tool_use_id: "other", blocks: [text("Not mine")] },
    });
    expect(await within(page).findByText("Found it in app/form.tsx")).toBeInTheDocument();
    expect(within(page).queryByText("Not mine")).not.toBeInTheDocument();

    // Once it finishes, its report is read again.
    api.agentTranscript.mockResolvedValueOnce({
      tool_use_id: "x1",
      prompt: "Find the form",
      messages: [{ event_id: 7, ts: "x", blocks: [text("Found it in app/form.tsx")] }],
      report: "[Subagent hand-back] The report follows:\n  The form is in app/form.tsx.",
    });
    push({
      type: "session.agents",
      session_id: "s1",
      payload: { agents: [trackedAgent({ id: "x1", status: "done" })] as never },
    });
    expect(await within(page).findByText("The form is in app/form.tsx.")).toBeInTheDocument();
    expect(within(page).getAllByText("Found it in app/form.tsx")).toHaveLength(1);
    expect(within(page).queryByText("Working")).not.toBeInTheDocument();
    expect(within(page).getByRole("img", { name: "Done" })).toBeInTheDocument();

    await user.click(within(page).getByRole("button", { name: "Back to Validate contact form" }));
    expect(screen.queryByRole("region", { name: "Explore" })).not.toBeInTheDocument();
  });

  it("says when the transcript cannot be read", async () => {
    const api = setup();
    api.agentTranscript.mockRejectedValueOnce(new ApiError(404, "no agent call 'x1'"));
    const { user } = await openList(api);

    await user.click(screen.getByRole("button", { name: "Explore, Find the form, working" }));
    expect(await screen.findByText("This subagent's work could not be read.")).toBeInTheDocument();
  });

  it("keeps what it showed once the subagent and then its chat are gone", async () => {
    const api = setup();
    api.agentTranscript.mockResolvedValueOnce({
      tool_use_id: "x1",
      prompt: null,
      messages: [],
      report: null,
    });
    const { user, push } = await openList(api);
    await user.click(screen.getByRole("button", { name: "Explore, Find the form, working" }));
    await screen.findByRole("region", { name: "Explore" });

    push({ type: "session.agents", session_id: "s1", payload: { agents: [] } });
    const page = await screen.findByRole("region", { name: "Subagent" });
    expect(within(page).queryByRole("img")).not.toBeInTheDocument();
    expect(within(page).queryByText("Find the form")).not.toBeInTheDocument();
    push({ type: "session.deleted", session_id: "s1", payload: { session_id: "s1" } });
    expect(await within(page).findByRole("button", { name: "Back to Chat" })).toBeInTheDocument();
  });

  it("drops a transcript that arrives after the page closed", async () => {
    const api = setup();
    const late = deferred<AgentWork>();
    api.agentTranscript.mockReturnValueOnce(late.promise);
    const { user } = await openList(api);
    await user.click(screen.getByRole("button", { name: "Explore, Find the form, working" }));
    await user.click(screen.getByRole("button", { name: "Back to Validate contact form" }));

    late.resolve({ tool_use_id: "x1", prompt: "Late", messages: [], report: null });
    await act(() => Promise.resolve());
    expect(screen.queryByText("Late")).not.toBeInTheDocument();
  });
});

describe("a pixie's work in a chat (B46)", () => {
  const solo = groupEntry({
    pixie_id: "scribe",
    state: "running",
    calls: [
      callEntry({ id: "c2", tool_use_id: "s1x", continued: true, state: "running" }),
      callEntry({ id: "c1", tool_use_id: "a1" }),
    ],
  });

  it("lists every call newest first, the continued one marked, and follows it live", async () => {
    const api = setup({ s1: [solo] });
    api.pixieCalls.mockResolvedValue([
      callWork({
        id: "c2",
        tool_use_id: "s1x",
        continued: true,
        state: "running",
        started_at: "2026-10-06T10:05:00Z",
        prompt: "Which one?",
        messages: [{ event_id: 9, ts: "x", blocks: [text("Thinking it over")] }],
      }),
      callWork({
        id: "c1",
        tool_use_id: "a1",
        started_at: "2026-10-06T10:00:00Z",
        prompt: "Pick an animal",
        messages: [{ event_id: 4, ts: "x", blocks: [text("picked")] }],
        report: "ok",
      }),
    ]);
    const { user, push } = await openList(api);

    await user.click(screen.getByRole("button", { name: "Scribe, working" }));
    const page = await screen.findByRole("region", { name: "Scribe" });
    expect(api.pixieCalls).toHaveBeenCalledWith("s1", "scribe");
    const calls = await within(page).findAllByRole("region", { name: /call,/i });
    expect(calls.map((c) => c.getAttribute("aria-label"))).toEqual([
      "Continued call, Working",
      "Call, Done",
    ]);
    expect(within(page).getByRole("img", { name: "Working" })).toHaveClass("ff");
    expect(within(defined(calls[0])).getByText("Continued")).toBeInTheDocument();
    expect(within(defined(calls[0])).getByText("Which one?")).toBeInTheDocument();
    expect(within(defined(calls[1])).getByText("ok")).toBeInTheDocument();

    // The continued agent's messages name its first call; they go to the running call.
    push({
      id: 10,
      type: "session.message",
      session_id: "s1",
      payload: { parent_tool_use_id: "a1", blocks: [text("platypus")] },
    });
    expect(await within(defined(calls[0])).findByText("platypus")).toBeInTheDocument();
    expect(within(defined(calls[1])).queryByText("platypus")).not.toBeInTheDocument();

    // The group changes: the calls are read again.
    push({
      type: "session.pixies",
      session_id: "s1",
      payload: {
        group: [
          {
            ...solo,
            state: "done",
            calls: solo.calls.map((c) => ({ ...c, state: "done" })),
          },
        ] as never,
      },
    });
    await waitFor(() => {
      expect(api.pixieCalls).toHaveBeenCalledTimes(2);
    });

    // Sent away elsewhere: it says so.
    push({ type: "session.pixies", session_id: "s1", payload: { group: [] } });
    expect(await within(page).findByText("Not in this chat any more.")).toBeInTheDocument();
  });

  it("shows a team's calls with who made each, and a member's own calls", async () => {
    const qa = groupEntry({
      kind: "team",
      pixie_id: null,
      team_id: "qa",
      state: "done",
      members: [
        { pixie_id: "lead", leader: true, state: "done" },
        { pixie_id: "bugs", leader: false, state: "done" },
        { pixie_id: "gone", leader: false, state: null },
      ],
      calls: [
        callEntry({ id: "b1", pixie_id: "bugs", tool_use_id: "t2" }),
        callEntry({ id: "l1", pixie_id: "lead", tool_use_id: "t1" }),
      ],
    });
    const api = setup({ s1: [qa] });
    api.pixieCalls.mockImplementation((_session, id) =>
      Promise.resolve(
        id === "lead"
          ? [
              callWork({ id: "l1", pixie_id: "lead", started_at: "2026-10-06T10:00:00Z" }),
              // Made alone, before it joined the team: not the team's.
              callWork({ id: "l0", pixie_id: "lead", started_at: "2026-10-05T10:00:00Z" }),
            ]
          : id === "bugs"
            ? [callWork({ id: "b1", pixie_id: "bugs", started_at: "2026-10-06T10:01:00Z" })]
            : [],
      ),
    );
    const { user } = await openList(api);

    await user.click(screen.getByRole("button", { name: "QA crew, @qa, done" }));
    // The pixie list's team section has the same name; the page is the pushed one.
    const page = defined(
      (await screen.findAllByRole("region", { name: "QA crew" })).find((r) =>
        r.classList.contains("push"),
      ),
    );
    expect(api.pixieCalls.mock.calls.map(([, id]) => id).sort()).toEqual(["bugs", "lead"]);
    const calls = await within(page).findAllByRole("region", { name: /call,/i });
    expect(calls.map((c) => within(c).getByText(/^(Lead|Bugs)$/).textContent)).toEqual([
      "Bugs",
      "Lead",
    ]);
    await user.click(within(page).getByRole("button", { name: "Back to Validate contact form" }));

    await user.click(await screen.findByRole("button", { name: "Lead, leader, done" }));
    const lead = await screen.findByRole("region", { name: "Lead" });
    expect(await within(lead).findAllByRole("region", { name: /call,/i })).toHaveLength(2);
    expect(within(lead).getByRole("img", { name: "Done" })).toBeInTheDocument();
    await user.click(within(lead).getByRole("button", { name: "Back to Validate contact form" }));

    // A member not called yet has no calls.
    await user.click(await screen.findByRole("button", { name: "A pixie, not called yet" }));
    expect(await screen.findByText("No calls yet.")).toBeInTheDocument();
  });

  it("says when the calls cannot be read", async () => {
    const api = setup({ s1: [solo] });
    api.pixieCalls.mockRejectedValueOnce(new Error("down"));
    const { user } = await openList(api);

    await user.click(screen.getByRole("button", { name: "Scribe, working" }));
    expect(await screen.findByText("This work could not be read.")).toBeInTheDocument();
  });

  it("marks a failed call and follows a call whose agent is not known yet", async () => {
    const api = setup({
      s1: [
        groupEntry({
          pixie_id: "scribe",
          state: "running",
          calls: [
            callEntry({ id: "c3", tool_use_id: "a3", agent_id: null, state: "running" }),
            callEntry({ id: "c1", tool_use_id: "a1", state: "failed" }),
          ],
        }),
      ],
    });
    api.pixieCalls.mockResolvedValueOnce([
      callWork({ id: "c3", tool_use_id: "a3", agent_id: null, state: "running" }),
      callWork({ id: "c1", tool_use_id: "a1", state: "failed" }),
    ]);
    const { user, push } = await openList(api);

    await user.click(screen.getByRole("button", { name: "Scribe, working" }));
    const failed = await screen.findByRole("region", { name: "Call, Failed" });
    expect(within(failed).getByText("Failed")).toHaveClass("bad");
    push({
      id: 20,
      type: "session.message",
      session_id: "s1",
      payload: { parent_tool_use_id: "a3", blocks: [text("on it")] },
    });
    const running = screen.getByRole("region", { name: "Call, Working" });
    expect(await within(running).findByText("on it")).toBeInTheDocument();
  });

  it("names a pixie or team it no longer knows, and a team sent away", async () => {
    const gone = groupEntry({
      kind: "team",
      pixie_id: null,
      team_id: "old",
      members: [{ pixie_id: "ghost", leader: true, state: "done" }],
      calls: [callEntry({ id: "g1", pixie_id: "ghost" })],
    });
    const api = setup({ s1: [groupEntry({ pixie_id: "ghost" }), gone] });
    api.pixieCalls.mockResolvedValue([callWork({ id: "g1", pixie_id: "ghost" })]);
    const { user, push } = await openList(api);

    await user.click(screen.getByRole("button", { name: "A pixie, done" }));
    expect(await screen.findByRole("region", { name: "A pixie" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to Validate contact form" }));

    await user.click(await screen.findByRole("button", { name: "A team, done" }));
    const page = await screen.findByRole("region", { name: "A team" });
    // Made by a pixie it no longer knows: no name on the call.
    expect(await within(page).findByRole("region", { name: "Call, Done" })).toBeInTheDocument();
    push({ type: "session.pixies", session_id: "s1", payload: { group: [] } });
    expect(await within(page).findByText("Not in this chat any more.")).toBeInTheDocument();
    expect(await within(page).findByText("No calls yet.")).toBeInTheDocument();
    push({ type: "session.deleted", session_id: "s1", payload: { session_id: "s1" } });
    expect(await within(page).findByRole("button", { name: "Back to Chat" })).toBeInTheDocument();
  });

  it("drops calls that arrive after the page closed", async () => {
    const api = setup({ s1: [solo] });
    const late = deferred<CallWork[]>();
    api.pixieCalls.mockReturnValueOnce(late.promise);
    const { user } = await openList(api);
    await user.click(screen.getByRole("button", { name: "Scribe, working" }));
    await user.click(screen.getByRole("button", { name: "Back to Validate contact form" }));

    late.resolve([callWork({ prompt: "Late" })]);
    await act(() => Promise.resolve());
    expect(screen.queryByText("Late")).not.toBeInTheDocument();
  });
});

describe("sprites at work in a pixie's or team's work (B48)", () => {
  const header = (page: HTMLElement) => defined(page.querySelector(".ch-t"));

  it("hops the pixie's header sprite while its call runs, and rests once it is done", async () => {
    const solo = groupEntry({ pixie_id: "scribe", state: "running" });
    const api = setup({ s1: [solo] });
    api.pixieCalls.mockResolvedValue([callWork({ state: "running" })]);
    const { user, push } = await openList(api);

    await user.click(screen.getByRole("button", { name: "Scribe, working" }));
    const page = await screen.findByRole("region", { name: "Scribe" });
    expect(header(page).querySelector("svg")).toHaveClass("pxwork");
    push({
      type: "session.pixies",
      session_id: "s1",
      payload: { group: [{ ...solo, state: "done" }] as never },
    });
    await waitFor(() => {
      expect(header(page).querySelector("svg")).not.toHaveClass("pxwork");
    });
  });

  it("shows a team as its grid of four, and hops each running call's maker", async () => {
    const qa = groupEntry({
      kind: "team",
      pixie_id: null,
      team_id: "qa",
      state: "running",
      members: [
        { pixie_id: "bugs", leader: false, state: "running" },
        { pixie_id: "lead", leader: true, state: "done" },
      ],
      calls: [
        callEntry({ id: "b1", pixie_id: "bugs", tool_use_id: "t2", state: "running" }),
        callEntry({ id: "l1", pixie_id: "lead", tool_use_id: "t1" }),
      ],
    });
    const api = setup({ s1: [qa] });
    api.pixieCalls.mockImplementation((_session, id) =>
      Promise.resolve(
        id === "lead"
          ? [callWork({ id: "l1", pixie_id: "lead", started_at: "2026-10-06T10:00:00Z" })]
          : [
              callWork({
                id: "b1",
                pixie_id: "bugs",
                state: "running",
                started_at: "2026-10-06T10:01:00Z",
              }),
            ],
      ),
    );
    const { user } = await openList(api);

    await user.click(screen.getByRole("button", { name: "QA crew, @qa, working" }));
    const page = defined(
      (await screen.findAllByRole("region", { name: "QA crew" })).find((r) =>
        r.classList.contains("push"),
      ),
    );
    const faces = [...header(page).querySelectorAll(".wkteam svg")];
    // The leader first, then Bugs, repeated; only Bugs is at work.
    expect(faces.map((f) => f.classList.contains("pxwork"))).toEqual([false, true, false, true]);
    const calls = await within(page).findAllByRole("region", { name: /call,/i });
    expect(calls.map((c) => c.querySelector(".wkby svg")?.classList.contains("pxwork"))).toEqual([
      true,
      false,
    ]);
  });
});
