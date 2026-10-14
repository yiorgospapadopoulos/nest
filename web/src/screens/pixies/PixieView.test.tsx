import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { fakeApi } from "../../test/fakeApi.ts";
import { detail, event, pixie, session } from "../../test/fixtures.ts";
import { openPixie } from "../../test/pixies.ts";

const chat = session({ id: "c1", title: "Tester", repo: "pixie:p1", pixie_id: "p1" });

describe("Pixie page", () => {
  it("says hi with no chat yet and sends through the pixie", async () => {
    const api = fakeApi();
    const { user } = await openPixie(api);

    expect(screen.getByText("Say hi to Tester")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Tester" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Attach" })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Message"), "hello");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(api.sendToPixie).toHaveBeenCalledWith("p1", "hello");
    await waitFor(() => {
      expect(screen.getByLabelText("Message")).toHaveValue("");
    });
  });

  it("keeps the message when sending fails and offers no slash commands", async () => {
    const api = fakeApi();
    api.sendToPixie.mockRejectedValueOnce(new Error("Mac asleep"));
    const { user } = await openPixie(api);

    await user.type(screen.getByLabelText("Message"), "/");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(api.sessionCommands).not.toHaveBeenCalled();
    expect(api.repoCommands).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Message"), "hi{Enter}");

    expect(await screen.findByText("Mac asleep")).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toHaveValue("/hi");
  });

  it("shows the pixie's chat transcript", async () => {
    const api = fakeApi();
    api.session.mockResolvedValue(detail(chat));
    api.sessionEvents.mockResolvedValue([
      event({
        id: 2,
        session_id: "c1",
        type: "session.user_message",
        payload: { text: "How are the tests?", attachments: [] },
      }),
    ]);
    await openPixie(api, pixie({ chat_session_id: "c1" }));

    expect(await screen.findByText("How are the tests?")).toBeInTheDocument();
    expect(api.session).toHaveBeenCalledWith("c1");
    expect(screen.queryByText("Say hi to Tester")).not.toBeInTheDocument();
    // Each run starts fresh, so earlier runs' checkpoints are gone (D072).
    expect(
      screen.queryByRole("button", { name: "Restore files to before this message" }),
    ).not.toBeInTheDocument();
  });

  it("loads the pixie's chat again from Retry", async () => {
    const api = fakeApi();
    // Known from an earlier event, as the session list leaves pixie chats out.
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
    api.session.mockResolvedValue(detail(chat));
    api.sessionEvents.mockRejectedValueOnce(new Error("Request failed (502)"));
    api.sessionEvents.mockResolvedValue([
      event({
        id: 2,
        session_id: "c1",
        type: "session.user_message",
        payload: { text: "Still there?", attachments: [] },
      }),
    ]);
    const { user } = await openPixie(api, pixie({ chat_session_id: "c1" }));

    await user.click(await screen.findByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Still there?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("interrupts the pixie while it works", async () => {
    const api = fakeApi();
    const running = { ...chat, state: "running" as const };
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [running]));
    api.session.mockResolvedValue(detail(running));
    const { user } = await openPixie(api, pixie({ chat_session_id: "c1" }));

    await user.click(await screen.findByRole("button", { name: "Interrupt" }));
    expect(api.interrupt).toHaveBeenCalledWith("c1");
    await user.type(screen.getByLabelText("Message"), "and then");
    expect(screen.getByRole("button", { name: "Queue" })).toBeEnabled();
  });

  it("uses the pixie's background", async () => {
    const { container } = await openPixie(fakeApi(), pixie({ background: "dusk" }));

    expect(container.ownerDocument.querySelector(".pxbg-dusk")).not.toBeNull();
  });

  it("switches between chat and details", async () => {
    const { user } = await openPixie();

    await user.click(screen.getByRole("tab", { name: "Details" }));
    expect(screen.getByRole("tab", { name: "Details", selected: true })).toBeInTheDocument();
    expect(screen.queryByLabelText("Message")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset conversation" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Chat" }));
    expect(screen.getByLabelText("Message")).toBeInTheDocument();
  });

  it("goes back when the pixie is deleted elsewhere", async () => {
    const { push } = await openPixie();

    push({ type: "pixie.deleted", session_id: null, payload: { pixie_id: "p1" } });
    await waitFor(() => {
      expect(screen.queryByRole("tab", { name: "Chat" })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: /Pixies/ })).toBeInTheDocument();
  });
});
