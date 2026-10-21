import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GroupEntry, Session } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import {
  callEntry,
  detail,
  groupEntry,
  pixie,
  repo,
  session,
  team,
  trackedAgent,
} from "../../test/fixtures.ts";
import { defined } from "../../test/defined.ts";
import { reduceMotion } from "../../test/motion.ts";
import { phaseOffset } from "../pixies/motion.ts";
import { renderApp } from "../../test/render.tsx";

const SCRIBE = pixie({ id: "scribe", slug: "scribe", name: "Scribe", color: "#E5484D" });
const LEAD = pixie({ id: "lead", slug: "lead", name: "Lead", team_id: "qa", color: "#30A46C" });
const BUGS = pixie({ id: "bugs", slug: "bugs", name: "Bugs", team_id: "qa", position: 1 });
const QA = team({ id: "qa", name: "QA crew", handle: "qa", leader_id: "lead" });

const SOLO = groupEntry({ pixie_id: "scribe", state: "running", calls: [callEntry()] });
const TEAM = groupEntry({
  kind: "team",
  pixie_id: null,
  team_id: "qa",
  state: "done",
  members: [
    { pixie_id: "lead", leader: true, state: "done" },
    { pixie_id: "bugs", leader: false, state: "running" },
  ],
  calls: [callEntry({ id: "c2", pixie_id: "lead", tool_use_id: "a2" })],
});

function withTree(chats: Session[], groups: Record<string, GroupEntry[]>): FakeApi {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : chats));
  api.pixies.mockResolvedValue([SCRIBE, LEAD, BUGS]);
  api.teams.mockResolvedValue([QA]);
  api.pixieGroups.mockResolvedValue(groups);
  return api;
}

async function openList(api: FakeApi) {
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  return rendered;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const tree = (title: string) => screen.getByRole("list", { name: `Working in ${title}` });

describe("each chat's tree (B46)", () => {
  it("shows a chat's pixies, a team with its members, and its running subagents", async () => {
    const chat = session({ state: "running" });
    const api = withTree([chat, session({ id: "s2", title: "Quiet chat" })], { s1: [SOLO, TEAM] });
    api.session.mockResolvedValue(
      detail({
        ...chat,
        agents: [
          trackedAgent({ id: "main", name: "main" }),
          trackedAgent({ id: "x1", name: "Explore", description: "Find the form" }),
          trackedAgent({ id: "x2", name: "Plan", description: null, parent: "x1" }),
          trackedAgent({ id: "x3", name: "Done one", status: "done" }),
          // The pixie's own call is listed among the pixies, not here.
          trackedAgent({ id: "a1", name: "scribe" }),
        ],
      }),
    );
    await openList(api);

    const list = await waitFor(() => tree("Validate contact form"));
    const pixies = within(list).getByRole("group", { name: "Pixies" });
    expect(within(pixies).getByRole("button", { name: "Scribe, working" })).toBeInTheDocument();
    const crew = within(pixies).getByRole("button", { name: "QA crew, @qa, done" });
    expect(crew.querySelector(".pxtname")).toHaveStyle({ "--px": "#30A46C" });
    expect(within(pixies).getByRole("button", { name: "Lead, leader, done" })).toBeInTheDocument();
    expect(within(pixies).getByRole("button", { name: "Bugs, working" })).toBeInTheDocument();
    expect(
      within(pixies).getByRole("button", { name: "Actions for Scribe in Validate contact form" }),
    ).toBeInTheDocument();
    expect(
      within(pixies).getByRole("button", {
        name: "Actions for team QA crew in Validate contact form",
      }),
    ).toBeInTheDocument();

    const subagents = within(list).getByRole("group", { name: "Subagents" });
    const explore = within(subagents).getByRole("button", {
      name: "Explore, Find the form, working",
    });
    // Plan was started by Explore, so it shows one level deeper.
    const nested = explore.closest("li")?.querySelector("ul");
    expect(
      within(nested as HTMLElement).getByRole("button", { name: "Plan, working" }),
    ).toBeInTheDocument();
    expect(within(subagents).getAllByRole("button")).toHaveLength(2);
    // A running subagent's row shows the working fireflies (B80).
    expect(explore.querySelector(".ff")).not.toBeNull();
    // A chat with nothing working has no tree.
    expect(screen.queryByRole("list", { name: "Working in Quiet chat" })).not.toBeInTheDocument();
  });

  it("hops the sprites whose calls run, and shows a team as a grid of four (B48)", async () => {
    const api = withTree([session()], { s1: [SOLO, TEAM] });
    await openList(api);

    const list = await waitFor(() => tree("Validate contact form"));
    const face = (name: string) =>
      defined(within(list).getByRole("button", { name }).querySelector(".ctic"));
    expect(face("Scribe, working").querySelector("svg")).toHaveClass("pxwork");
    expect(face("Lead, leader, done").querySelector("svg")).not.toHaveClass("pxwork");
    expect(face("Bugs, working").querySelector("svg")).toHaveClass("pxwork");
    // A running call says so with fireflies beside the sprite, a finished one with its word (B80).
    expect(
      within(list).getByRole("button", { name: "Scribe, working" }).querySelector(".ff"),
    ).not.toBeNull();
    expect(
      within(list).getByRole("button", { name: "Lead, leader, done" }).querySelector(".ff"),
    ).toBeNull();

    // The leader first, then the members in order, repeated to fill the four cells;
    // only the member at work hops.
    const grid = face("QA crew, @qa, done");
    expect(grid).toHaveClass("ctteam");
    const faces = [...grid.querySelectorAll("svg")];
    expect(faces.map((f) => f.querySelector("rect")?.getAttribute("fill"))).toEqual([
      LEAD.color,
      BUGS.color,
      LEAD.color,
      BUGS.color,
    ]);
    expect(faces.map((f) => f.classList.contains("pxwork"))).toEqual([false, true, false, true]);
    expect(faces.map((f) => f.getAttribute("width"))).toEqual(["10", "10", "10", "10"]);
    // Bugs, shown twice, hops apart from itself: each cell has its own phase.
    const phase = (cell: number) => defined(faces[cell]).style.getPropertyValue("--pxph");
    expect(phase(1)).toBe(`-${String(phaseOffset("bugs#1"))}ms`);
    expect(phase(3)).toBe(`-${String(phaseOffset("bugs#3"))}ms`);
    expect(phase(1)).not.toBe(phase(3));
  });

  it("keeps every sprite still under Reduce Motion, the working dots saying it (B48)", async () => {
    reduceMotion(true);
    const api = withTree([session()], { s1: [SOLO, TEAM] });
    await openList(api);

    const list = await waitFor(() => tree("Validate contact form"));
    expect(list.querySelectorAll("svg.pxwork")).toHaveLength(0);
    for (const name of ["Scribe, working", "Bugs, working"]) {
      expect(within(list).getByRole("button", { name }).querySelector(".ff")).not.toBeNull();
    }
  });

  it("keeps a team's generic mark while it has no members (B48)", async () => {
    const api = withTree([session()], { s1: [{ ...TEAM, members: [] }] });
    await openList(api);

    const list = await waitFor(() => tree("Validate contact form"));
    const crew = within(list).getByRole("button", { name: "QA crew, @qa, done" });
    expect(crew.querySelector(".ctteam")).toBeNull();
    expect(crew.querySelector(".ctic .ic")).toBeInTheDocument();
  });

  it("follows the groups and subagents live", async () => {
    const api = withTree([session()], {});
    const { push } = await openList(api);
    expect(screen.queryByRole("list", { name: /^Working in/ })).not.toBeInTheDocument();

    push({ type: "session.pixies", session_id: "s1", payload: { group: [SOLO] as never } });
    push({
      type: "session.agents",
      session_id: "s1",
      payload: { agents: [trackedAgent({ id: "x1", description: null })] as never },
    });
    const list = tree("Validate contact form");
    expect(within(list).getByRole("button", { name: "Scribe, working" })).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: "Explore, working" })).toBeInTheDocument();

    // A subagent that is done leaves; the pixie stays once it finished.
    push({
      type: "session.agents",
      session_id: "s1",
      payload: { agents: [trackedAgent({ id: "x1", status: "done" })] as never },
    });
    push({
      type: "session.pixies",
      session_id: "s1",
      payload: { group: [{ ...SOLO, state: "done" }] as never },
    });
    expect(within(list).getByRole("button", { name: "Scribe, done" })).toBeInTheDocument();
    expect(within(list).queryByRole("group", { name: "Subagents" })).not.toBeInTheDocument();
  });

  it("names states, and a pixie or member it no longer knows", async () => {
    const api = withTree([session()], {
      s1: [
        groupEntry({ pixie_id: "scribe", state: "failed" }),
        groupEntry({ pixie_id: "gone", state: "interrupted" }),
        groupEntry({
          kind: "team",
          pixie_id: null,
          team_id: "old",
          state: "done",
          members: [{ pixie_id: "gone", leader: true, state: null }],
        }),
      ],
    });
    await openList(api);

    const list = await waitFor(() => tree("Validate contact form"));
    expect(within(list).getByRole("button", { name: "Scribe, failed" })).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: "A pixie, stopped" })).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: "A team, done" })).toBeInTheDocument();
    expect(
      within(list).getByRole("button", { name: "A pixie, leader, not called yet" }),
    ).toBeInTheDocument();
  });

  it("sends a pixie or a team away from the chat", async () => {
    const api = withTree([session()], { s1: [SOLO, TEAM] });
    api.sendAway.mockResolvedValueOnce([TEAM]).mockResolvedValueOnce([]);
    const { user } = await openList(api);
    await waitFor(() => tree("Validate contact form"));

    await user.click(
      screen.getByRole("button", { name: "Actions for Scribe in Validate contact form" }),
    );
    const sheet = screen.getByRole("dialog", { name: "Scribe" });
    await user.click(within(sheet).getByRole("menuitem", { name: /Send away/ }));
    expect(api.sendAway).toHaveBeenCalledWith("s1", { pixie_id: "scribe" });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Scribe, working" })).not.toBeInTheDocument();
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Actions for team QA crew in Validate contact form" }),
    );
    await user.click(screen.getByRole("menuitem", { name: /Send away/ }));
    expect(api.sendAway).toHaveBeenLastCalledWith("s1", { team_id: "qa" });
    await waitFor(() => {
      expect(screen.queryByRole("list", { name: /^Working in/ })).not.toBeInTheDocument();
    });
  });

  it("keeps the menu open when sending away fails, and closes it on Cancel", async () => {
    const api = withTree([session()], { s1: [SOLO] });
    api.sendAway.mockRejectedValueOnce(new Error("down"));
    const { user } = await openList(api);
    await waitFor(() => tree("Validate contact form"));

    await user.click(
      screen.getByRole("button", { name: "Actions for Scribe in Validate contact form" }),
    );
    await user.click(screen.getByRole("menuitem", { name: /Send away/ }));
    expect(await screen.findByText("down")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Scribe, working" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
