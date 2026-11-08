// Computer use on the phone (B150): the strip with Stop while the chat holds an app.
import { act, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { COMPUTER_STATE } from "../../api/events.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { detail, event, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

beforeEach(() => {
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:frame");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
});

describe("computer use on the phone (B150)", () => {
  it("shows the strip while the chat holds an app and stops from it", async () => {
    const api = fakeApi();
    const chat = session();
    api.computerSettings.mockResolvedValue({ enabled: true, pixies: false });
    api.repos.mockResolvedValue([repo("todo-ui")]);
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
    api.session.mockResolvedValue(detail(chat));
    api.sessionEvents.mockResolvedValue([
      event({
        id: 3,
        type: COMPUTER_STATE,
        payload: { targets: [{ key: "ios:A1", name: "iOS Simulator" }] },
      }),
    ]);
    const { user, sockets } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));

    const strip = await screen.findByRole("group", { name: "Using iOS Simulator" });
    await waitFor(() => {
      expect(strip.querySelector("img")).toHaveAttribute("src", "blob:frame");
    });
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(api.stopComputerUse).toHaveBeenCalledWith("s1");

    act(() => {
      sockets.last().emit({ id: 4, session_id: "s1", type: COMPUTER_STATE, payload: {} });
    });
    expect(screen.queryByRole("group", { name: "Using iOS Simulator" })).not.toBeInTheDocument();
  });
});
