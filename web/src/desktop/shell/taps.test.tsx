// Regression (VM, 2026-11-03): a click with no time between press and release, as xdotool
// or a quick touchpad tap makes, did not select a project tab in WebKitGTK. A press and a
// release on the same spot must act, whether or not the engine then sends a click.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Actions } from "../../store/actions.ts";
import { StoreContext } from "../../store/context.ts";
import { initialState } from "../../store/state.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { repo, session } from "../../test/fixtures.ts";
import { ApiContext } from "../context.ts";
import { ProjectState } from "../layout/project.ts";
import { ShellContext, type Shell } from "./context.ts";
import { EMPTY_DESK } from "./desk.ts";
import { Sidebar } from "./Sidebar.tsx";
import { TabStrip } from "./TabStrip.tsx";

function setup() {
  const shell = {
    desk: {
      ...EMPTY_DESK,
      tabs: { open: ["todo-ui", "map-viewer"], current: "todo-ui", last: "todo-ui" },
    },
    project: "todo-ui",
    repo: repo("todo-ui"),
    state: new ProjectState(),
    selectTab: vi.fn(),
    moveTab: vi.fn(),
    closeTab: vi.fn(),
    openPane: vi.fn(),
    newChat: vi.fn(),
    openSettings: vi.fn(),
    setPalette: vi.fn(),
  } as unknown as Shell;
  const state = {
    ...initialState,
    repos: [repo("todo-ui"), repo("map-viewer")],
    sessions: { s1: session({ id: "s1", title: "Fix the header" }) },
  };
  const actions = { loadAccounts: vi.fn(), onEvent: () => () => undefined } as unknown as Actions;
  render(
    <ApiContext value={fakeApi()}>
      <StoreContext value={{ state, actions, address: "127.0.0.1:8765" }}>
        <ShellContext value={shell}>
          <TabStrip />
          <Sidebar />
        </ShellContext>
      </StoreContext>
    </ApiContext>,
  );
  return shell;
}

const press = (element: Element, x = 10) => {
  fireEvent.pointerDown(element, { button: 0, pointerId: 1, clientX: x, clientY: 10 });
};
const release = (element: Element, x = 10) => {
  fireEvent.pointerUp(element, { button: 0, pointerId: 1, clientX: x, clientY: 10 });
};

describe("a quick tap", () => {
  it("selects a project tab with no time and no move between press and release", () => {
    const shell = setup();
    const tab = screen.getByRole("tab", { name: "map-viewer" });
    press(tab);
    release(tab);
    expect(shell.selectTab).toHaveBeenCalledWith("map-viewer");
  });

  it("selects the tab once when the engine also sends its click", () => {
    const shell = setup();
    const tab = screen.getByRole("tab", { name: "map-viewer" });
    press(tab);
    release(tab);
    fireEvent.click(tab, { detail: 1 });
    expect(shell.selectTab).toHaveBeenCalledTimes(1);
  });

  it("still selects from the keyboard, and a drag moves the tab instead", () => {
    const shell = setup();
    const tab = screen.getByRole("tab", { name: "map-viewer" });
    fireEvent.click(tab, { detail: 0 });
    expect(shell.selectTab).toHaveBeenCalledWith("map-viewer");
    vi.mocked(shell.selectTab).mockClear();
    press(tab, 10);
    fireEvent.pointerMove(tab, { button: 0, pointerId: 1, clientX: -200, clientY: 10 });
    release(tab, -200);
    expect(shell.moveTab).toHaveBeenCalledWith("map-viewer", 0);
    expect(shell.selectTab).not.toHaveBeenCalled();
  });

  it("opens a sidebar chat row, which also drags into the workspace", () => {
    const shell = setup();
    const row = screen.getByRole("button", { name: /^Fix the header/ });
    press(row);
    release(row);
    expect(shell.openPane).toHaveBeenCalledWith("s1");
  });
});
