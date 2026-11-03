// A click on the pill's approval opens its chat, the project's panel on Needs you, and that
// approval's row there, as the Mac's island click does (IslandController.openApproval).
import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NestEvent } from "../../api/types.ts";
import type { Actions } from "../../store/actions.ts";
import { StoreContext } from "../../store/context.ts";
import { initialState } from "../../store/state.ts";
import { approval, session } from "../../test/fixtures.ts";
import { browserBridge, type Bridge, type OpenTarget } from "../bridge.ts";
import { BridgeContext } from "../context.ts";
import { ProjectState } from "../layout/project.ts";
import type { Shell } from "./context.ts";
import { approvalFoldKey, useRowOpen } from "./frame/foldRows.ts";
import { useWindowWatch } from "./useWindowWatch.ts";

it("opens the approval's Needs you row on the pill's needs-you click", () => {
  const pending = approval({ id: "a1", session_id: "s1", repo: "todo-ui" });
  let open: ((target: OpenTarget) => void) | null = null;
  const bridge: Bridge = {
    ...browserBridge({ search: "" }, null),
    onOpenRequest: (callback) => {
      open = callback;
      return () => undefined;
    },
  };
  const shell = {
    project: "todo-ui",
    state: new ProjectState(),
    openChat: vi.fn(),
    showNeedsYou: vi.fn(),
  } as unknown as Shell;
  const state = {
    ...initialState,
    sessions: { s1: session({ id: "s1" }) },
    approvals: { a1: pending },
  };
  const actions = { onEvent: () => () => undefined } as unknown as Actions;
  let rowOpen = false;
  function Probe() {
    useWindowWatch(shell);
    [rowOpen] = useRowOpen(approvalFoldKey(pending), false);
    return null;
  }
  render(
    <BridgeContext value={bridge}>
      <StoreContext value={{ state, actions, address: "127.0.0.1:8765" }}>
        <Probe />
      </StoreContext>
    </BridgeContext>,
  );
  expect(rowOpen).toBe(false);
  act(() => {
    open?.({ chat: "s1", approval: "a1" });
  });
  expect(shell.openChat).toHaveBeenCalledWith("s1");
  expect(shell.showNeedsYou).toHaveBeenCalledWith("todo-ui");
  expect(rowOpen).toBe(true);
});

describe("a notice while the window is minimised", () => {
  function watch(manager: { minimized: boolean; visible: boolean } | null) {
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
    let send: ((event: NestEvent) => void) | null = null;
    const notify = vi.fn(() => Promise.resolve());
    const bridge: Bridge = {
      ...browserBridge({ search: "" }, null),
      notify,
      windowState: () => Promise.resolve(manager),
    };
    const project = new ProjectState();
    project.openChat("s1", { width: 1000, height: 600 });
    const shell = { project: "todo-ui", state: project } as unknown as Shell;
    const actions = {
      onEvent: (listener: (event: NestEvent) => void) => {
        send = listener;
        return () => undefined;
      },
    } as unknown as Actions;
    function Probe() {
      useWindowWatch(shell);
      return null;
    }
    render(
      <BridgeContext value={bridge}>
        <StoreContext value={{ state: initialState, actions, address: "127.0.0.1:8765" }}>
          <Probe />
        </StoreContext>
      </BridgeContext>,
    );
    const finish = async () => {
      await act(async () => {
        send?.({
          id: 1,
          ts: new Date().toISOString(),
          session_id: "s1",
          type: "notify",
          payload: {
            kind: "finished",
            session_id: "s1",
            repo: "todo-ui",
            title: "Fix",
            text: "Done.",
          },
        });
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    };
    return { notify, finish };
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("notifies though X11 still calls the minimised window focused (wave 6)", async () => {
    const { notify, finish } = watch({ minimized: true, visible: false });
    await finish();
    expect(notify).toHaveBeenCalledWith("todo-ui · Fix", "Done.", "s1", false);
  });

  it("stays quiet about the chat on screen in the window in use", async () => {
    const { notify, finish } = watch({ minimized: false, visible: true });
    await finish();
    expect(notify).not.toHaveBeenCalled();
  });
});
