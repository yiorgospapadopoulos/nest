// The frame's menus and rows wired to what they do: the + popover's Add folder, inline
// rename, the project menu's Project settings and New terminal, the Terminal button, and an
// approval's Needs you row unfolding from outside (the pill).
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  BranchMap,
  BranchMapBranch,
  EarlierWorktree,
  NestEvent,
  RepoConfig,
  SelectPlaceBody,
} from "../../../api/types.ts";
import type { Actions } from "../../../store/actions.ts";
import { StoreContext } from "../../../store/context.ts";
import { initialState, type State } from "../../../store/state.ts";
import { fakeApi } from "../../../test/fakeApi.ts";
import { approval, repo, session } from "../../../test/fixtures.ts";
import { browserBridge, type Bridge } from "../../bridge.ts";
import { ApiContext, BridgeContext } from "../../context.ts";
import { ProjectState } from "../../layout/project.ts";
import { ShellContext, type Shell } from "../context.ts";
import { EMPTY_DESK } from "../desk.ts";
import { RightPanel } from "../RightPanel.tsx";
import { Sidebar } from "../Sidebar.tsx";
import { StatusBar } from "../StatusBar.tsx";
import { TabStrip } from "../TabStrip.tsx";
import * as lanes from "./branchLanes.ts";
import { setRowOpen, unfoldApproval } from "./foldRows.ts";
import { useGonePlaces } from "./projectMap.ts";

function setup(
  options: {
    pick?: string | null;
    state?: Partial<State>;
    map?: BranchMap;
    selected?: RepoConfig["selected_place"];
    project?: Partial<RepoConfig>;
  } = {},
) {
  const project = new ProjectState();
  const shell = {
    desk: { ...EMPTY_DESK, tabs: { open: ["todo-ui"], current: "todo-ui", last: "todo-ui" } },
    project: "todo-ui",
    repo: { ...repo("todo-ui"), selected_place: options.selected ?? null, ...options.project },
    state: project,
    update: vi.fn((change: (s: ProjectState) => void) => {
      change(project);
    }),
    workspaceSize: () => ({ width: 1200, height: 800 }),
    selectTab: vi.fn(),
    openProject: vi.fn(),
    openPane: vi.fn(),
    openChat: vi.fn(),
    closePane: vi.fn(),
    newChat: vi.fn(),
    newWorktreeFrom: vi.fn(),
    newBrowser: vi.fn(),
    openIn: vi.fn(),
    openSettings: vi.fn(),
    setPalette: vi.fn(),
    toggleSidebar: vi.fn(),
    toggleActivity: vi.fn(),
    setView: vi.fn(),
  } as unknown as Shell;
  const state: State = {
    ...initialState,
    repos: [repo("todo-ui"), repo("map-viewer")],
    sessions: { s1: session({ id: "s1", title: "Fix the header" }) },
    ...options.state,
  };
  const receive = vi.fn();
  const update = vi.fn().mockResolvedValue(true);
  const api = fakeApi();
  if (options.map !== undefined) api.branchMap.mockResolvedValue(options.map);
  const listeners = new Set<(event: NestEvent) => void>();
  const refreshRepo = vi.fn().mockResolvedValue(undefined);
  const actions = {
    loadAccounts: vi.fn(),
    loadGoals: vi.fn(),
    onEvent: (listener: (event: NestEvent) => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    receive,
    refreshRepo,
    selectPlace: (name: string, body: SelectPlaceBody) => api.selectPlace(name, body),
    refreshRemotes: (name: string) => api.refreshRemotes(name),
    // As the real action: a failure is a toast and null.
    trackRemoteBranch: (name: string, remote: string, branch: string) =>
      api.trackRemoteBranch(name, remote, branch).then(
        (made) => made.branch,
        () => null,
      ),
    toast: vi.fn(),
    update,
  } as unknown as Actions;
  api.registerRepo.mockResolvedValue(repo("new-folder"));
  const bridge: Bridge = {
    ...browserBridge({ search: "" }, null),
    pickFolder: vi.fn().mockResolvedValue(options.pick ?? null),
  };
  render(
    <BridgeContext value={bridge}>
      <ApiContext value={api}>
        <StoreContext value={{ state, actions, address: "127.0.0.1:8765" }}>
          <ShellContext value={shell}>
            <TabStrip />
            <Sidebar />
            <RightPanel />
            <StatusBar />
          </ShellContext>
        </StoreContext>
      </ApiContext>
    </BridgeContext>,
  );
  const emit = (event: Partial<NestEvent> & { type: string }) => {
    act(() => {
      for (const listener of listeners) {
        listener({ id: 1, session_id: null, payload: {}, ...event } as NestEvent);
      }
    });
  };
  return { shell, api, project, receive, update, emit, refreshRepo };
}

const openMenu = (button: HTMLElement) => {
  fireEvent.pointerDown(button, { button: 0 });
  fireEvent.pointerUp(document.body, { button: 0 });
};

const branch = (
  name: string,
  parent: string | null,
  extra: Partial<BranchMapBranch> = {},
): BranchMapBranch => ({
  name,
  parent,
  worktree: null,
  here: false,
  behind: 0,
  remote: null,
  ...extra,
});

const branchMap: BranchMap = {
  default_branch: "main",
  current_branch: "wip",
  detached: false,
  branches: [
    branch("main", null, { behind: 3 }),
    branch("wip", "main", { here: true }),
    branch("feat/a", "wip", { worktree: { path: "/w/a", owner: "nest" }, behind: 2 }),
    branch("feat/b", "main"),
  ],
  remote_branches: [{ remote: "origin", name: "feat/only-there" }],
};

describe("the branch map (B131)", () => {
  const opened = async (options: Parameters<typeof setup>[0] = {}) => {
    const tools = setup({ map: branchMap, ...options });
    await screen.findByRole("button", { name: /^Branch / });
    await act(async () => {
      setRowOpen("branch-map-todo-ui", true);
      await Promise.resolve();
    });
    await screen.findByRole("region", { name: "Branch map" });
    return tools;
  };
  // Remote picks hold by the clock, past one test's end.
  let now = 1_000_000;
  beforeEach(() => {
    now += 1000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
  });
  afterEach(() => {
    vi.mocked(Date.now).mockRestore();
    act(() => {
      setRowOpen("branch-map-todo-ui", false);
    });
  });
  const row = (name: string | RegExp) => screen.getByRole("button", { name });

  it("reads the map again on repo.branches_changed and on opening", async () => {
    const { api, emit, refreshRepo } = setup({ map: branchMap });
    await waitFor(() => {
      expect(api.branchMap).toHaveBeenCalled();
    });

    api.branchMap.mockClear();
    emit({ type: "repo.branches_changed", payload: { name: "other-project" } });
    expect(api.branchMap).not.toHaveBeenCalled();
    emit({ type: "repo.branches_changed", payload: { name: "todo-ui" } });
    expect(api.branchMap).toHaveBeenCalledTimes(1);
    expect(refreshRepo).toHaveBeenCalledWith("todo-ui");

    api.branchMap.mockClear();
    refreshRepo.mockClear();
    fireEvent.click(await screen.findByRole("button", { name: /show branch map/ }));
    expect(api.branchMap).toHaveBeenCalledTimes(1);
    expect(refreshRepo).toHaveBeenCalledWith("todo-ui");
  });

  it("sends the selection on a click and opens no pane", async () => {
    const { api, shell } = await opened();
    fireEvent.click(row(/^feat\/b/));
    expect(api.selectPlace).toHaveBeenCalledWith("todo-ui", { branch: "feat/b" });
    fireEvent.click(row(/^feat\/a/));
    expect(api.selectPlace).toHaveBeenCalledWith("todo-ui", { worktree_path: "/w/a" });
    expect(shell.newChat).not.toHaveBeenCalled();
    expect(shell.openPane).not.toHaveBeenCalled();
    expect(shell.newWorktreeFrom).not.toHaveBeenCalled();
  });

  it("selects in the full tree and leaves the sheet open, with the mark moved", async () => {
    const { api, shell } = await opened({ selected: { branch: "wip", worktree_path: null } });
    fireEvent.click(row("Full tree"));
    const sheet = screen.getByRole("dialog", { name: "Branches and worktrees" });
    expect(within(sheet).getByRole("button", { name: /^wip/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    fireEvent.click(within(sheet).getByRole("button", { name: /^feat\/b/ }));
    expect(api.selectPlace).toHaveBeenCalledWith("todo-ui", { branch: "feat/b" });
    expect(shell.newChat).not.toHaveBeenCalled();
    expect(shell.openPane).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Branches and worktrees" })).toBeInTheDocument();
    fireEvent.keyDown(sheet, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers a new worktree on every row, without selecting it", async () => {
    const { api, shell } = await opened();
    for (const name of ["main", "wip", "feat/a", "feat/b"]) {
      expect(row(`New worktree from ${name}`)).toBeInTheDocument();
    }
    fireEvent.click(row("New worktree from feat/a"));
    expect(shell.newWorktreeFrom).toHaveBeenCalledWith("feat/a");
    expect(api.selectPlace).not.toHaveBeenCalled();
  });

  it("notes what is behind on the rows that are, and only in the map", async () => {
    await opened();
    expect(row(/^main/)).toHaveTextContent("3 behind");
    expect(row(/^feat\/a/)).toHaveTextContent("2 behind");
    expect(row(/^feat\/b/)).not.toHaveTextContent("behind");
  });

  it("makes the local branch for a remote row, then selects it", async () => {
    const { api } = await opened();
    api.trackRemoteBranch.mockResolvedValue({ branch: "feat/only-there" });
    fireEvent.click(row(/^On remotes/));
    fireEvent.click(row("feat/only-there on origin"));
    await waitFor(() => {
      expect(api.selectPlace).toHaveBeenCalledWith("todo-ui", { branch: "feat/only-there" });
    });
    expect(api.trackRemoteBranch).toHaveBeenCalledWith("todo-ui", "origin", "feat/only-there");
  });

  describe("a double click on a remote row (B131)", () => {
    const remote = () => screen.getByRole("button", { name: "feat/only-there on origin" });
    const onlyThere: BranchMap = {
      ...branchMap,
      remote_branches: [
        { remote: "origin", name: "feat/only-there" },
        { remote: "origin", name: "feat/next" },
      ],
    };

    it("sends one POST for two picks in quick succession", async () => {
      const { api } = await opened({ map: onlyThere });
      api.trackRemoteBranch.mockResolvedValue({ branch: "feat/only-there" });
      fireEvent.click(row(/^On remotes/));
      fireEvent.click(remote());
      // While the pick runs, and in the pause after it, with the next row under the pointer.
      fireEvent.click(row("feat/next on origin"));
      await waitFor(() => {
        expect(api.selectPlace).toHaveBeenCalledTimes(1);
      });
      fireEvent.click(row("feat/next on origin"));
      fireEvent.click(row(/^feat\/b/));
      await act(async () => {
        await Promise.resolve();
      });
      expect(api.trackRemoteBranch).toHaveBeenCalledTimes(1);
      expect(api.selectPlace).toHaveBeenCalledTimes(1);

      now += 601;
      fireEvent.click(row("feat/next on origin"));
      expect(api.trackRemoteBranch).toHaveBeenCalledTimes(2);
    });

    it("holds a pick from Find too, so the row that comes back is not picked", async () => {
      const { api } = await opened();
      fireEvent.change(screen.getByLabelText("Find a branch"), { target: { value: "feat/b" } });
      fireEvent.click(row("feat/b"));
      // The list is back, with another row under the pointer.
      fireEvent.click(row(/^main/));
      await waitFor(() => {
        expect(api.selectPlace).toHaveBeenCalledWith("todo-ui", { branch: "feat/b" });
      });
      fireEvent.click(row(/^main/));
      expect(api.selectPlace).toHaveBeenCalledTimes(1);

      // A slow double click, still inside the hold.
      now += 500;
      fireEvent.click(row(/^main/));
      expect(api.selectPlace).toHaveBeenCalledTimes(1);

      now += 101;
      await act(async () => {
        await Promise.resolve();
      });
      fireEvent.click(row(/^main/));
      expect(api.selectPlace).toHaveBeenLastCalledWith("todo-ui", { branch: "main" });
    });

    it("ends the hold after a failed pick too", async () => {
      const { api } = await opened({ map: onlyThere });
      api.trackRemoteBranch.mockRejectedValueOnce(new Error("refused"));
      api.trackRemoteBranch.mockResolvedValue({ branch: "feat/only-there" });
      fireEvent.click(row(/^On remotes/));
      fireEvent.click(remote());
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      now += 601;
      fireEvent.click(remote());
      expect(api.trackRemoteBranch).toHaveBeenCalledTimes(2);
    });
  });

  it("marks a remote-only top row with its remote, with no new worktree", async () => {
    const { api } = await opened({
      map: {
        ...branchMap,
        branches: [branch("main", null, { remote: "origin" }), ...branchMap.branches.slice(1)],
      },
    });
    expect(row(/^main/)).toHaveTextContent("origin");
    expect(screen.queryByRole("button", { name: "New worktree from main" })).toBeNull();
    fireEvent.click(row(/^main/));
    await waitFor(() => {
      expect(api.trackRemoteBranch).toHaveBeenCalledWith("todo-ui", "origin", "main");
    });
  });

  it("shows no fold without remotes, and a detached folder as a row nothing selects", async () => {
    const { api } = await opened({
      map: {
        ...branchMap,
        current_branch: null,
        detached: true,
        remote_branches: [],
        branches: branchMap.branches.map((b) => ({ ...b, here: false })),
      },
    });
    expect(screen.queryByRole("button", { name: /^On remotes/ })).toBeNull();
    const detached = screen.getByText("detached");
    fireEvent.click(detached);
    expect(api.selectPlace).not.toHaveBeenCalled();
    // Under the top row, never over it.
    const names = [...document.querySelectorAll(".fr-bmap .fr-bmrow")].map((r) => r.textContent);
    expect(names[0]).toContain("main");
    expect(names[1]).toContain("detached");
  });

  const detachedMap: BranchMap = {
    ...branchMap,
    current_branch: null,
    detached: true,
    branches: branchMap.branches.map((b) => ({ ...b, here: false })),
  };
  const detachedRepo = { current_branch: null };

  it("says detached on the chip while new chats run in the detached folder", async () => {
    await opened({ map: detachedMap, project: detachedRepo });
    expect(row(/^Branch detached/)).toHaveTextContent("detached");
  });

  it("keeps the default branch on the chip when the folder only has no branch name", async () => {
    // A broken repo, or an unborn orphan branch among others.
    await opened({ map: { ...detachedMap, detached: false }, project: detachedRepo });
    expect(row(/^Branch main/)).toBeInTheDocument();
    expect(screen.queryByText("detached")).toBeNull();
  });

  it("keeps the default branch on the chip until the map says otherwise", async () => {
    const tools = setup({ project: detachedRepo });
    await waitFor(() => {
      expect(tools.api.branchMap).toHaveBeenCalled();
    });
    expect(row(/^Branch main/)).toBeInTheDocument();
  });

  it("clears the selection from the detached row, and only with one to clear", async () => {
    const { api } = await opened({
      map: detachedMap,
      project: detachedRepo,
      selected: { branch: "feat/b", worktree_path: null },
    });
    expect(row(/^Branch feat\/b/)).toBeInTheDocument();
    fireEvent.click(row("detached, here"));
    expect(api.selectPlace).toHaveBeenCalledWith("todo-ui", {});
  });

  it("brings a row picked from Find into view only once the selection has landed", async () => {
    const landed = vi.fn<(value: RepoConfig) => void>();
    const { api } = await opened();
    api.selectPlace.mockReturnValue(
      new Promise((resolve) => {
        landed.mockImplementation(resolve);
      }),
    );
    const reveal = vi.spyOn(lanes, "revealSelected");
    reveal.mockClear();
    fireEvent.change(screen.getByLabelText("Find a branch"), { target: { value: "feat/b" } });
    fireEvent.click(row("feat/b"));
    expect(reveal).not.toHaveBeenCalled();
    await act(async () => {
      landed(repo("todo-ui"));
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(reveal).toHaveBeenCalled();
    });
    reveal.mockRestore();
  });

  it("re-reads at once, then fetches, then re-reads, and reports a failed remote", async () => {
    const { api, refreshRepo } = await opened();
    api.branchMap.mockClear();
    let finish: (report: Awaited<ReturnType<typeof api.refreshRemotes>>) => void = () => undefined;
    api.refreshRemotes.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    fireEvent.click(row("Reload"));
    expect(api.branchMap).toHaveBeenCalledTimes(1);
    expect(refreshRepo).toHaveBeenCalled();
    await waitFor(() => {
      expect(api.refreshRemotes).toHaveBeenCalledWith("todo-ui");
    });
    expect(row("Reload")).toHaveAttribute("aria-busy", "true");
    // The map stays usable while the fetch runs.
    fireEvent.click(row(/^feat\/b/));
    expect(api.selectPlace).toHaveBeenCalled();
    await act(async () => {
      finish({
        remotes: [
          { name: "origin", error: null },
          { name: "upstream", error: "Could not resolve host" },
        ],
      });
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(api.branchMap).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("Could not resolve host")).toBeInTheDocument();
    fireEvent.click(row("Dismiss"));
    expect(screen.queryByText("Could not resolve host")).toBeNull();
  });
});

describe("a selected place that is gone (B131)", () => {
  function Watch() {
    useGonePlaces();
    return null;
  }
  const gone = (name: string | null, place: RepoConfig["selected_place"] = null) => ({
    ...repo("todo-ui"),
    selected_place: place,
    selected_place_gone: name,
  });
  const shown = (repos: RepoConfig[], actions: Actions) => (
    <StoreContext value={{ state: { ...initialState, repos }, actions, address: "" }}>
      <Watch />
    </StoreContext>
  );
  const watcher = () => {
    const toast = vi.fn();
    const clearGonePlace = vi.fn().mockResolvedValue(undefined);
    return { toast, clearGonePlace, actions: { toast, clearGonePlace } as unknown as Actions };
  };

  it("toasts once and clears it when it is there on first load", () => {
    const { actions, toast, clearGonePlace } = watcher();
    const view = render(shown([gone("wip")], actions));
    expect(toast).toHaveBeenCalledWith(
      "wip is gone. New chats start in the project folder.",
      "info",
    );
    expect(clearGonePlace).toHaveBeenCalledWith("todo-ui");

    // Still reported while the clear is in flight, and from a read that crossed it.
    view.rerender(shown([gone("wip")], actions));
    view.rerender(shown([gone(null)], actions));
    view.rerender(shown([gone("wip")], actions));
    expect(toast).toHaveBeenCalledTimes(1);
    expect(clearGonePlace).toHaveBeenCalledTimes(1);
  });

  it("tells again once a new selection has gone too, and never for a clear by click", () => {
    const { actions, toast } = watcher();
    const view = render(shown([gone("wip")], actions));
    view.rerender(shown([gone(null, { branch: "wip", worktree_path: null })], actions));
    view.rerender(shown([gone(null)], actions));
    expect(toast).toHaveBeenCalledTimes(1);
    view.rerender(shown([gone("wip")], actions));
    expect(toast).toHaveBeenCalledTimes(2);
  });
});

describe("a chat's earlier worktrees (B119)", () => {
  const moved = (earlier: EarlierWorktree[]) => ({
    state: {
      sessions: { moved: session({ id: "moved", title: "Moved", earlier_worktrees: earlier }) },
    },
  });

  it("fold out beneath the row without opening the chat", () => {
    const { shell } = setup(
      moved([
        {
          path: "/w/gone",
          branch: "agent/gone",
          base_ref: null,
          started_at: "2026-11-04T10:00:00Z",
          ended_at: "2026-11-04T11:00:00Z",
          state: "deleted",
        },
      ]),
    );
    const toggle = screen.getByRole("button", { name: "Earlier worktrees of Moved" });
    expect(screen.queryByText("deleted")).toBeNull();

    fireEvent.pointerDown(toggle, { button: 0 });
    fireEvent.pointerUp(toggle, { button: 0 });
    fireEvent.click(toggle);

    expect(shell.openPane).not.toHaveBeenCalled();
    expect(screen.getByText("deleted")).toBeInTheDocument();
    expect(screen.getByTitle("agent/gone")).toBeInTheDocument();
  });

  it("show nothing on a chat that never moved", () => {
    setup(moved([]));
    expect(screen.queryByRole("button", { name: /^Earlier worktrees/ })).toBeNull();
  });
});

describe("a project tab's status", () => {
  const tab = () => document.querySelector(".dk-proj");
  const chat = (state: "running" | "idle") => ({
    sessions: { s1: session({ id: "s1", repo: "todo-ui", state }) },
  });

  it("shows the fireflies while a chat runs, even with something waiting, and no number", () => {
    setup({ state: { ...chat("running"), approvals: { q1: approval({ repo: "todo-ui" }) } } });
    expect(tab()?.querySelector(".ff")).not.toBeNull();
    expect(tab()?.querySelector(".dot")).toBeNull();
    expect(tab()).not.toHaveTextContent("1");
  });

  it("shows a dot and no number when nothing runs and something waits", () => {
    setup({ state: { ...chat("idle"), approvals: { q1: approval({ repo: "todo-ui" }) } } });
    expect(tab()?.querySelector(".dot.s-wait")).not.toBeNull();
    expect(tab()?.querySelector(".ff")).toBeNull();
    expect(tab()).not.toHaveTextContent("1");
  });

  it("shows a green dot for finished work alone, amber as soon as anything else waits", () => {
    const review = approval({ id: "r1", repo: "todo-ui", kind: "review" });
    setup({ state: { ...chat("idle"), approvals: { r1: review } } });
    expect(tab()?.querySelector(".dot.s-rev")).not.toBeNull();
    cleanup();

    const ask = approval({ id: "q1", repo: "todo-ui" });
    setup({ state: { ...chat("idle"), approvals: { r1: review, q1: ask } } });
    expect(tab()?.querySelector(".dot.s-wait")).not.toBeNull();
    expect(tab()?.querySelector(".dot.s-rev")).toBeNull();
  });

  it("shows nothing when nothing runs or waits", () => {
    setup({ state: chat("idle") });
    expect(tab()?.querySelector(".ff, .dot")).toBeNull();
  });
});

describe("the + popover", () => {
  it("lists General and the closed projects, and opens one", () => {
    const { shell } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Open another project" }));
    const popover = screen.getByRole("dialog", { name: "Open another project" });
    expect(popover).toHaveTextContent("GeneralChats with no project");
    fireEvent.click(screen.getByRole("button", { name: /^map-viewer/ }));
    expect(shell.openProject).toHaveBeenCalledWith("map-viewer");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("registers a picked new folder and opens it", async () => {
    const { shell, api, receive } = setup({ pick: "/Users/me/new-folder" });
    fireEvent.click(screen.getByRole("button", { name: "Open another project" }));
    fireEvent.click(screen.getByRole("button", { name: "Add folder…" }));
    await waitFor(() => {
      expect(shell.openProject).toHaveBeenCalledWith("new-folder");
    });
    expect(api.registerRepo).toHaveBeenCalledWith("/Users/me/new-folder");
    expect(receive).toHaveBeenCalledWith(expect.objectContaining({ type: "repo.added" }));
  });

  it("opens a picked folder that is already a project without registering it again", async () => {
    const { shell, api } = setup({ pick: "/Users/me/map-viewer" });
    fireEvent.click(screen.getByRole("button", { name: "Open another project" }));
    fireEvent.click(screen.getByRole("button", { name: "Add folder…" }));
    await waitFor(() => {
      expect(shell.openProject).toHaveBeenCalledWith("map-viewer");
    });
    expect(api.registerRepo).not.toHaveBeenCalled();
  });
});

describe("a chat row", () => {
  it("renames in place from its menu: Enter saves, Escape keeps the name", () => {
    const { update } = setup();
    const row = screen.getByRole("button", { name: /^Fix the header/ });
    fireEvent.contextMenu(row, { clientX: 40, clientY: 40 });
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const field = screen.getByRole("textbox", { name: "Rename chat" });
    fireEvent.change(field, { target: { value: "Fix the footer" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(update).toHaveBeenCalledWith("s1", { title: "Fix the footer" });
    expect(screen.queryByRole("textbox", { name: "Rename chat" })).toBeNull();

    update.mockClear();
    openMenu(screen.getByRole("button", { name: "Actions for Fix the header" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const again = screen.getByRole("textbox", { name: "Rename chat" });
    fireEvent.change(again, { target: { value: "Something else" } });
    fireEvent.keyDown(again, { key: "Escape" });
    expect(update).not.toHaveBeenCalled();
  });

  it("asks before deleting", () => {
    setup();
    fireEvent.contextMenu(screen.getByRole("button", { name: /^Fix the header/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete…" }));
    expect(screen.getByRole("alertdialog", { name: "Delete this chat?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});

describe("the project menu", () => {
  it("opens Settings on the project's page", () => {
    const { shell } = setup();
    openMenu(screen.getByRole("button", { name: "Project todo-ui" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Project settings…" }));
    expect(shell.openSettings).toHaveBeenCalledWith({ project: "todo-ui" });
  });

  it("always opens one more terminal from New terminal", () => {
    const { project } = setup();
    for (let i = 0; i < 2; i++) {
      openMenu(screen.getByRole("button", { name: "Project todo-ui" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "New terminal" }));
    }
    expect(project.openTools.filter((p) => p.kind === "terminal")).toHaveLength(2);
  });
});

describe("the Terminal button", () => {
  it("opens where the focused chat works, and reuses that terminal", () => {
    const { project } = setup();
    project.openChat("s1", { width: 1200, height: 800 });
    fireEvent.click(screen.getByRole("button", { name: "Terminal" }));
    project.openChat("s1", { width: 1200, height: 800 });
    fireEvent.click(screen.getByRole("button", { name: "Terminal" }));
    const terminals = project.openTools.filter((p) => p.kind === "terminal");
    expect(terminals.map((p) => p.folder)).toEqual(["/w/s1"]);
  });
});

describe("Needs you", () => {
  it("unfolds an approval's row when the pill asks", () => {
    const pending = approval({ id: "a1", session_id: "s1", repo: "todo-ui" });
    setup({ state: { approvals: { a1: pending } } });
    const toggle = screen.getAllByRole("button", { name: "Show details" })[0];
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    act(() => {
      unfoldApproval(pending);
    });
    expect(screen.getAllByRole("button", { name: "Hide details" })[0]).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});
