// The frame's menus and rows wired to what they do: the + popover's Add folder, inline
// rename, the project menu's Project settings and New terminal, the Terminal button, and an
// approval's Needs you row unfolding from outside (the pill).
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
import { unfoldApproval } from "./foldRows.ts";

function setup(options: { pick?: string | null; state?: Partial<State> } = {}) {
  const project = new ProjectState();
  const shell = {
    desk: { ...EMPTY_DESK, tabs: { open: ["todo-ui"], current: "todo-ui", last: "todo-ui" } },
    project: "todo-ui",
    repo: repo("todo-ui"),
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
  const actions = {
    loadAccounts: vi.fn(),
    loadGoals: vi.fn(),
    onEvent: () => () => undefined,
    receive,
    toast: vi.fn(),
    update,
  } as unknown as Actions;
  const api = fakeApi();
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
  return { shell, api, project, receive, update };
}

const openMenu = (button: HTMLElement) => {
  fireEvent.pointerDown(button, { button: 0 });
  fireEvent.pointerUp(document.body, { button: 0 });
};

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
