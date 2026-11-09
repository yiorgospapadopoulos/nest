import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../../../test/fakeApi.ts";
import { socketFactory } from "../../../test/fakeSocket.ts";
import { memoryStorage } from "../../../test/render.tsx";
import { browserBridge, type Bridge } from "../../bridge.ts";
import { DesktopApp } from "../../DesktopApp.tsx";

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

const INSTALL = {
  updating: null,
  releaseUrl: "https://github.com/yiorgospapadopoulos/nest/releases/latest/download",
  released: true,
};

async function openGeneral(bridge: Partial<Bridge>, api = fakeApi()) {
  const storage = memoryStorage();
  render(
    <DesktopApp
      bridge={{ ...browserBridge({ search: "" }, null), native: true, ...bridge }}
      api={api}
      connect={socketFactory().connect}
      location={{ protocol: "http:", host: "127.0.0.1:41053" }}
      storage={() => storage}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
  const pages = screen.getByRole("navigation", { name: "Settings pages" });
  fireEvent.click(within(pages).getByRole("button", { name: "General" }));
  return api;
}

describe("Uninstall Nest", () => {
  it("keeps chats, settings and secrets unless the user chooses to delete them", async () => {
    const uninstall = vi.fn(() => Promise.resolve());
    await openGeneral({ installState: () => Promise.resolve(INSTALL), uninstall });

    fireEvent.click(await screen.findByRole("button", { name: "Uninstall" }));
    let dialog = screen.getByRole("alertdialog", { name: "Uninstall Nest?" });
    expect(within(dialog).getByRole("switch")).not.toBeChecked();
    fireEvent.click(within(dialog).getByRole("button", { name: "Uninstall" }));
    expect(uninstall).toHaveBeenLastCalledWith(false);

    fireEvent.click(screen.getByRole("button", { name: "Uninstall" }));
    dialog = screen.getByRole("alertdialog", { name: "Uninstall Nest?" });
    fireEvent.click(within(dialog).getByRole("switch"));
    expect(dialog).toHaveTextContent("your chats, settings and secrets are deleted");
    fireEvent.click(within(dialog).getByRole("button", { name: "Uninstall" }));
    expect(uninstall).toHaveBeenLastCalledWith(true);
  });

  it("is not offered on a developer's checkout", async () => {
    const installState = vi.fn(() => Promise.resolve({ ...INSTALL, released: false }));
    await openGeneral({ installState });

    await waitFor(() => {
      expect(installState).toHaveBeenCalled();
    });
    expect(screen.getByText("Report a bug")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Uninstall" })).not.toBeInTheDocument();
  });
});

describe("a bug report", () => {
  it("carries the app's own answer and, when too long, shows its file for the issue", async () => {
    const api = fakeApi();
    api.setupReport.mockResolvedValue({
      path: "/home/me/.local/share/nest/reports/r.txt",
      text: "Nest report",
      issue_url: "https://github.com/yiorgospapadopoulos/nest/issues/new?title=Nest",
      attach_file: true,
    });
    const openExternal = vi.fn(() => Promise.resolve());
    const openPath = vi.fn(() => Promise.resolve());
    await openGeneral(
      { notificationServer: () => Promise.resolve("gnome-shell"), openExternal, openPath },
      api,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Report" }));
    fireEvent.click(await screen.findByRole("button", { name: "Report on GitHub" }));

    expect(api.setupReport).toHaveBeenCalledWith([
      expect.objectContaining({ id: "notifications", state: "ok", detail: "gnome-shell" }),
    ]);
    expect(openExternal).toHaveBeenCalledWith(
      "https://github.com/yiorgospapadopoulos/nest/issues/new?title=Nest",
    );
    expect(openPath).toHaveBeenCalledWith("/home/me/.local/share/nest/reports/r.txt", true);
  });
});

describe("Default editor (B152)", () => {
  it("lists the installed editors and saves the one picked", async () => {
    const api = fakeApi();
    const editors = {
      installed: [
        { id: "vscode" as const, name: "VS Code" },
        { id: "zed" as const, name: "Zed" },
      ],
      default: "vscode" as const,
    };
    api.editors.mockResolvedValue(editors);
    api.setDefaultEditor.mockResolvedValue({ ...editors, default: "zed" });
    await openGeneral({}, api);

    fireEvent.click(await screen.findByRole("button", { name: "Default editor: VS Code" }));
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Zed" }));

    expect(api.setDefaultEditor).toHaveBeenCalledWith("zed");
    expect(await screen.findByRole("button", { name: "Default editor: Zed" })).toBeVisible();
  });

  it("is not shown while no editor is installed", async () => {
    await openGeneral({});

    await screen.findByRole("button", { name: "Restart" });
    expect(screen.queryByText("Default editor")).toBeNull();
  });
});
