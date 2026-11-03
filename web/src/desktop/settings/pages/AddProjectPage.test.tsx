import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Actions } from "../../../store/actions.ts";
import { StoreContext } from "../../../store/context.ts";
import { initialState } from "../../../store/state.ts";
import { fakeApi } from "../../../test/fakeApi.ts";
import { repo } from "../../../test/fixtures.ts";
import { browserBridge } from "../../bridge.ts";
import { ApiContext, BridgeContext } from "../../context.ts";
import { ShellContext, type Shell } from "../../shell/context.ts";
import { AddProjectPage } from "./AddProjectPage.tsx";

function setup(registered = repo("todo-ui")) {
  const api = fakeApi();
  api.registerRepo.mockResolvedValue(registered);
  const shell = { openProject: vi.fn(), openSettings: vi.fn() } as unknown as Shell;
  const actions = { refreshRepo: vi.fn(), toast: vi.fn() };
  const state = { ...initialState, repos: [{ ...repo("nest"), path: "/home/me/nest" }] };
  render(
    <StoreContext
      value={{ state, actions: actions as unknown as Actions, address: "127.0.0.1:8765" }}
    >
      <ApiContext value={api}>
        <BridgeContext value={browserBridge({ search: "" }, null)}>
          <ShellContext value={shell}>
            <AddProjectPage />
          </ShellContext>
        </BridgeContext>
      </ApiContext>
    </StoreContext>,
  );
  const add = (path: string) => {
    fireEvent.change(screen.getByRole("textbox", { name: "Folder" }), {
      target: { value: path },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
  };
  return { api, shell, actions, add };
}

describe("Add project", () => {
  it("adds a new folder and opens the new project's Settings page", async () => {
    const { api, shell, actions, add } = setup({ ...repo("todo-ui"), path: "/home/me/todo-ui" });
    add("/home/me/todo-ui/");
    await waitFor(() => {
      expect(shell.openSettings).toHaveBeenCalledWith({ project: "todo-ui" });
    });
    expect(api.registerRepo).toHaveBeenCalledWith("/home/me/todo-ui");
    expect(actions.refreshRepo).toHaveBeenCalledWith("todo-ui");
  });

  it("opens a folder already added instead of adding it again", () => {
    const { api, shell, add } = setup();
    add("/home/me/nest");
    expect(api.registerRepo).not.toHaveBeenCalled();
    expect(shell.openProject).toHaveBeenCalledWith("nest");
    expect(shell.openSettings).toHaveBeenCalledWith({ project: "nest" });
  });

  it("says why a folder could not be added and stays on the page", async () => {
    const { api, shell, actions, add } = setup();
    api.registerRepo.mockRejectedValue(new Error("/nope: no such folder"));
    add("/nope");
    await waitFor(() => {
      expect(actions.toast).toHaveBeenCalledWith(
        "Could not add the project: /nope: no such folder",
        "error",
      );
    });
    expect(shell.openSettings).not.toHaveBeenCalled();
  });
});
