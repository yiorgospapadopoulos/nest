import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { repo } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { browserBridge } from "../bridge.ts";
import { DesktopApp } from "../DesktopApp.tsx";

beforeAll(() => {
  // jsdom has none; the workspace measures itself with one.
  globalThis.ResizeObserver = class {
    observe() {
      return undefined;
    }
    unobserve() {
      return undefined;
    }
    disconnect() {
      return undefined;
    }
  };
});

/** The desktop app with Settings open on the page named `page` in its list. */
async function openPage(api: ReturnType<typeof fakeApi>, page: string) {
  const storage = memoryStorage();
  render(
    <DesktopApp
      bridge={browserBridge({ search: "" }, null)}
      api={api}
      connect={socketFactory().connect}
      location={{ protocol: "http:", host: "127.0.0.1:8765" }}
      storage={() => storage}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
  const pages = screen.getByRole("navigation", { name: "Settings pages" });
  fireEvent.click(await within(pages).findByRole("button", { name: page }));
}

/** Types `text` in the open text alert and saves it. */
function typeAndSave(text: string) {
  const alert = within(screen.getByRole("alertdialog"));
  fireEvent.change(alert.getByRole("textbox"), { target: { value: text } });
  fireEvent.click(alert.getByRole("button", { name: "Save" }));
}

describe("worktree settings for every project", () => {
  it("saves the whole section, and an empty folder as inside each project", async () => {
    const api = fakeApi();
    api.worktreeSettings.mockResolvedValue({
      folder: "~/worktrees",
      branch_prefix: "agent/",
      clean_merged: false,
      submodules: false,
    });
    await openPage(api, "Agents");

    const change = await screen.findByRole("button", { name: "Change Worktrees folder" });
    await waitFor(() => {
      expect(change).toBeEnabled();
    });
    fireEvent.click(change);
    typeAndSave("  ");
    expect(api.saveWorktreeSettings).toHaveBeenLastCalledWith({
      folder: null,
      branch_prefix: "agent/",
      clean_merged: false,
      submodules: false,
    });
    expect(await screen.findByText("Inside each project")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Remove merged worktrees" }));
    expect(api.saveWorktreeSettings).toHaveBeenLastCalledWith({
      folder: null,
      branch_prefix: "agent/",
      clean_merged: true,
      submodules: false,
    });
  });

  it("shows the daemon's refusal and keeps the saved value", async () => {
    const api = fakeApi();
    api.saveWorktreeSettings.mockRejectedValue(
      new ApiError(422, "folder must be absolute or start with ~"),
    );
    await openPage(api, "Agents");

    const change = await screen.findByRole("button", { name: "Change Worktrees folder" });
    await waitFor(() => {
      expect(change).toBeEnabled();
    });
    fireEvent.click(change);
    typeAndSave("worktrees");

    expect(await screen.findByText(/folder must be absolute or start with ~/)).toBeInTheDocument();
    expect(screen.getByText("Inside each project")).toBeInTheDocument();
  });
});

describe("a project's own worktree choices", () => {
  it("sends only the choice changed, and null to follow the default again", async () => {
    const api = fakeApi();
    const project = repo("todo-ui");
    api.repos.mockResolvedValue([project]);
    api.updateRepo.mockImplementation((_, patch) =>
      Promise.resolve({ ...project, worktree: { ...project.worktree, ...patch } }),
    );
    await openPage(api, "todo-ui");
    fireEvent.click(screen.getByRole("tab", { name: "Worktrees" }));

    const submodules = within(screen.getByRole("radiogroup", { name: "Check out submodules" }));
    fireEvent.click(submodules.getByRole("radio", { name: "On" }));
    await waitFor(() => {
      expect(api.updateRepo).toHaveBeenLastCalledWith("todo-ui", { submodules: true });
    });
    await waitFor(() => {
      expect(submodules.getByRole("radio", { name: "On" })).toHaveAttribute("aria-checked", "true");
    });
    fireEvent.click(submodules.getByRole("radio", { name: "Follow default" }));
    await waitFor(() => {
      expect(api.updateRepo).toHaveBeenLastCalledWith("todo-ui", { submodules: null });
    });

    fireEvent.click(screen.getByRole("button", { name: "Change Branch name prefix" }));
    typeAndSave(" nest/ ");
    await waitFor(() => {
      expect(api.updateRepo).toHaveBeenLastCalledWith("todo-ui", { branch_prefix: "nest/" });
    });
  });
});
