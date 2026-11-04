import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StoreProvider } from "../../store/StoreProvider.tsx";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { engineUpdates } from "../../test/fixtures.ts";
import { UpdateRailDot, UpdateStrip } from "./UpdateStrip.tsx";

const READY = engineUpdates({
  state: "ready",
  engines: [{ id: "claude", name: "Claude Code", current: "2.1.317", new: "2.1.318" }],
});

function renderStrip(api = fakeApi()) {
  const sockets = socketFactory();
  render(
    <StoreProvider
      api={api}
      connect={sockets.connect}
      location={{ protocol: "http:", host: "127.0.0.1:41010" }}
    >
      <UpdateStrip />
      <UpdateRailDot />
    </StoreProvider>,
  );
  return { api, user: userEvent.setup() };
}

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe = vi.fn();
      disconnect = vi.fn();
    },
  );
});

describe("the left bar's update strip", () => {
  it("asks first when chats are mid-turn, and relaunches only once confirmed", async () => {
    const api = fakeApi();
    api.checkUpdates.mockResolvedValue(READY);
    const { user } = renderStrip(api);
    const relaunch = await screen.findByRole("button", { name: "Relaunch to update" });
    api.updates.mockResolvedValue({ ...READY, busy_chats: 1 });

    await user.click(relaunch);

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("1 chat is mid-turn");
    expect(api.relaunchUpdate).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Relaunch" }));

    expect(api.relaunchUpdate).toHaveBeenCalledOnce();
    expect(await screen.findByRole("button", { name: "Relaunching..." })).toBeDisabled();
  });

  it("hides with the x, dot included, without telling the daemon", async () => {
    const api = fakeApi();
    api.checkUpdates.mockResolvedValue(READY);
    const { user } = renderStrip(api);
    await user.click(await screen.findByRole("button", { name: "Hide for now" }));

    expect(screen.queryByRole("button", { name: "Relaunch to update" })).not.toBeInTheDocument();
    expect(screen.queryByTitle("Update available")).not.toBeInTheDocument();
    expect(api.dismissUpdateNotice).not.toHaveBeenCalled();
  });

  it("marks the squeezed bar", async () => {
    const api = fakeApi();
    api.checkUpdates.mockResolvedValue(READY);
    renderStrip(api);
    await waitFor(() => {
      expect(screen.getByTitle("Update available")).toBeInTheDocument();
    });
  });
});
