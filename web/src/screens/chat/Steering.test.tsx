import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { QueuedMessage, Session } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { detail, event, queuedMessage, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const SHOT = { id: "a1", filename: "shot.png", media_type: "image/png", size: 3 };

async function openChat({
  chat = session({ state: "running" }),
  queued = [],
  api = fakeApi(),
}: { chat?: Session; queued?: QueuedMessage[]; api?: FakeApi } = {}) {
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail({ ...chat, queued }));
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  return { ...rendered, field: screen.getByLabelText("Message") };
}

const pending = () => screen.getByRole("list", { name: "Pending messages" });
const queuedEvent = (id: number, queued: QueuedMessage[]) =>
  event({ id, type: "session.queued", payload: { queued: queued as never } });

describe("messages sent while Claude works (B59)", () => {
  it("sends normally and shows the message pending above the composer until Claude reads it", async () => {
    const { user, api, field, push, container } = await openChat();
    api.sendMessage.mockResolvedValue({
      ...session({ state: "running" }),
      queued_message: queuedMessage({ sent: true }),
    });

    await user.type(field, "Then add tests");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(api.sendMessage).toHaveBeenCalledWith("s1", "Then add tests", []);
    await waitFor(() => {
      expect(field).toHaveValue("");
    });

    push(queuedEvent(5, [queuedMessage({ sent: true, attachments: [SHOT] })]));
    const row = within(pending()).getByRole("listitem");
    expect(row).toHaveTextContent("Then add tests");
    expect(row).toHaveTextContent("shot.png");
    expect(row).toHaveTextContent("Claude reads this at its next step");
    // Not part of the transcript until Claude reads it.
    expect(defined(container.querySelector(".tx"))).not.toHaveTextContent("Then add tests");

    push(queuedEvent(6, []));
    push(
      event({
        id: 7,
        type: "session.user_message",
        payload: { text: "Then add tests", attachments: [] },
      }),
    );
    expect(screen.queryByRole("list", { name: "Pending messages" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Then add tests")).toHaveLength(1);
  });

  it.each([
    ["running", "Sends when this turn ends"],
    ["interrupted", "Waiting"],
  ] as const)("says when a message that waits goes out: %s", async (state, line) => {
    await openChat({ chat: session({ state }), queued: [queuedMessage()] });

    expect(within(pending()).getByRole("listitem")).toHaveTextContent(line);
  });

  it("shows the commands a pending message carries, not their tags", async () => {
    const text =
      "<bash-input>ls</bash-input>\n<bash-stdout>a</bash-stdout><bash-stderr></bash-stderr>\n\nWhy?";
    await openChat({ queued: [queuedMessage({ text })] });

    const row = within(pending()).getByRole("listitem");
    expect(row).toHaveTextContent("Why?");
    expect(row).toHaveTextContent("! ls");
    expect(row).not.toHaveTextContent("bash-input");
  });

  it("sends a pending message now, once until the list changes", async () => {
    const api = fakeApi();
    api.sendNow.mockRejectedValueOnce(new ApiError(500, "boom"));
    const { user, push } = await openChat({ api, queued: [queuedMessage()] });
    const button = () => within(pending()).getByRole("button", { name: "Send now" });

    await user.click(button());
    expect(await screen.findByText("boom")).toBeInTheDocument();
    expect(button()).toBeEnabled();

    await user.click(button());
    expect(api.sendNow.mock.calls).toEqual([
      ["s1", "m1"],
      ["s1", "m1"],
    ]);
    expect(button()).toBeDisabled();
    push(queuedEvent(5, [queuedMessage()]));
    expect(button()).toBeEnabled();
  });

  it("removes a pending message, unless Claude already read it", async () => {
    const api = fakeApi();
    api.cancelQueued
      .mockRejectedValueOnce(new ApiError(500, "boom"))
      .mockResolvedValueOnce(null)
      .mockRejectedValueOnce(new ApiError(409, "too late", "message_taken"));
    const { user } = await openChat({
      api,
      queued: [queuedMessage(), queuedMessage({ id: "m2", text: "And docs", sent: true })],
    });
    const remove = (n: number) =>
      defined(screen.getAllByRole("button", { name: "Remove pending message" })[n]);

    await user.click(remove(0));
    expect(await screen.findByText("boom")).toBeInTheDocument();
    expect(within(pending()).getByText("Then add tests")).toBeInTheDocument();
    await user.click(remove(0));
    await waitFor(() => {
      expect(screen.queryByText("Then add tests")).not.toBeInTheDocument();
    });
    await user.click(remove(0));
    expect(await screen.findByText("Claude already read this message")).toBeInTheDocument();
    expect(screen.queryByText("And docs")).not.toBeInTheDocument();
    expect(api.cancelQueued.mock.calls).toEqual([
      ["s1", "m1"],
      ["s1", "m1"],
      ["s1", "m2"],
    ]);
  });

  it("drops a pending message the Mac no longer knows", async () => {
    const api = fakeApi();
    api.cancelQueued.mockRejectedValueOnce(new ApiError(404, "no queued message"));
    const { user } = await openChat({ api, queued: [queuedMessage()] });

    await user.click(screen.getByRole("button", { name: "Remove pending message" }));

    expect(await screen.findByText("Claude already read this message")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Pending messages" })).not.toBeInTheDocument();
  });

  it("edits a pending message: takes it back into the composer", async () => {
    const { user, api, field } = await openChat({
      queued: [queuedMessage({ attachments: [SHOT] })],
    });

    await user.click(screen.getByRole("button", { name: "Edit pending message" }));

    expect(api.cancelQueued).toHaveBeenCalledWith("s1", "m1");
    await waitFor(() => {
      expect(field).toHaveValue("Then add tests");
    });
    expect(field).toHaveFocus();
    expect(screen.getByRole("button", { name: "Remove shot.png" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Pending messages" })).not.toBeInTheDocument();
  });

  it("leaves the composer alone when Claude already read the message", async () => {
    const api = fakeApi();
    api.cancelQueued.mockRejectedValueOnce(new ApiError(409, "too late", "message_taken"));
    const { user, field } = await openChat({ api, queued: [queuedMessage()] });

    await user.click(screen.getByRole("button", { name: "Edit pending message" }));

    expect(await screen.findByText("Claude already read this message")).toBeInTheDocument();
    expect(field).toHaveValue("");
  });

  it("asks before replacing what is typed, and can keep both", async () => {
    const { user, field } = await openChat({
      queued: [queuedMessage(), queuedMessage({ id: "m2", text: "And docs" })],
    });
    await user.type(field, "Draft");
    const edit = (n: number) =>
      defined(screen.getAllByRole("button", { name: "Edit pending message" })[n]);

    await user.click(edit(1));
    const ask = await screen.findByRole("alertdialog", { name: "Replace your message?" });
    await user.click(within(ask).getByRole("button", { name: "Keep both" }));
    expect(field).toHaveValue("Draft\n\nAnd docs");

    await user.click(edit(0));
    await user.click(await screen.findByRole("button", { name: "Replace" }));
    expect(field).toHaveValue("Then add tests");
    await waitFor(() => {
      expect(field).toHaveFocus();
    });
  });

  it("keeps what is typed when the question is cancelled", async () => {
    const { user, field } = await openChat({ queued: [queuedMessage()] });
    await user.type(field, "Draft");

    await user.click(screen.getByRole("button", { name: "Edit pending message" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(field).toHaveValue("Draft");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("offers no queue mode: the send button says Send while Claude works", async () => {
    const { user, field } = await openChat();

    expect(screen.getByRole("button", { name: "Interrupt" })).toBeInTheDocument();
    await user.type(field, "x");
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Queue" })).not.toBeInTheDocument();
  });
});
