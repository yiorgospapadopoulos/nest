import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Attachment } from "../../api/types.ts";
import { NAVIGATE } from "../../pwa/navigate.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { installBrowserPush, uninstallBrowserPush } from "../../test/fakePush.ts";
import { detail, event, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

afterEach(() => {
  uninstallBrowserPush();
});

const first = session({ id: "s1", title: "Fix login" });
const second = session({ id: "s2", title: "Add tests" });

const attachment = (id: string, filename: string): Attachment => ({
  id,
  filename,
  media_type: "text/plain",
  size: 1,
  created_at: "x",
});

/** Two chats in one project, with a way to jump between them as a notification tap does. */
async function twoChats() {
  const { worker } = installBrowserPush();
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [first, second]));
  api.session.mockImplementation((id) => Promise.resolve(detail(id === "s1" ? first : second)));
  api.sessionEvents.mockImplementation((id) =>
    Promise.resolve([
      event({
        id: id === "s1" ? 1 : 2,
        session_id: id,
        type: "session.message",
        payload: { blocks: [{ type: "text", text: `Hello from ${id}` }] },
      }),
    ]),
  );
  const rendered = await renderApp({ api });
  const go = async (id: string, title: string) => {
    act(() => {
      worker.dispatchEvent(
        new MessageEvent("message", { data: { type: NAVIGATE, url: `/chat/${id}` } }),
      );
    });
    await screen.findByRole("region", { name: title });
    await screen.findByText(`Hello from ${id}`);
  };
  return { ...rendered, go };
}

describe("switching chats", () => {
  it("keeps each chat's draft and attachments to itself, and restores them on return", async () => {
    const { user, api, go } = await twoChats();
    api.uploadAttachment.mockResolvedValueOnce(attachment("a1", "notes.txt"));

    await go("s1", "Fix login");
    await user.type(screen.getByLabelText("Message"), "Half typed for login");
    await user.upload(screen.getByLabelText("Attach files"), new File(["x"], "notes.txt"));
    expect(await screen.findByText("notes.txt")).toBeInTheDocument();

    await go("s2", "Add tests");
    expect(screen.getByLabelText("Message")).toHaveValue("");
    expect(screen.queryByText("notes.txt")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await user.type(screen.getByLabelText("Message"), "For the tests");

    await go("s1", "Fix login");
    expect(screen.getByLabelText("Message")).toHaveValue("Half typed for login");
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(api.sendMessage).toHaveBeenCalledWith("s1", "Half typed for login", ["a1"]);
    await waitFor(() => {
      expect(screen.getByLabelText("Message")).toHaveValue("");
    });

    // Going back and opening the chat again from the list restores its draft as well.
    await user.click(screen.getByRole("button", { name: /back/i }));
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: /^Add tests,/ }));
    await screen.findByRole("region", { name: "Add tests" });
    expect(screen.getByLabelText("Message")).toHaveValue("For the tests");
  });

  it("clears the draft of the chat a message went to, even after switching away", async () => {
    const { user, api, go } = await twoChats();
    let deliver: () => void = () => undefined;
    api.sendMessage.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          deliver = () => {
            resolve({ ...first, queued_message: null });
          };
        }),
    );

    await go("s1", "Fix login");
    await user.type(screen.getByLabelText("Message"), "Ship it");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await go("s2", "Add tests");
    await user.type(screen.getByLabelText("Message"), "Keep me");
    await act(async () => {
      deliver();
      await Promise.resolve();
    });

    expect(screen.getByLabelText("Message")).toHaveValue("Keep me");
    await go("s1", "Fix login");
    expect(screen.getByLabelText("Message")).toHaveValue("");
  });

  it("keeps an upload that finishes after switching with the chat it was added to", async () => {
    const { user, api, go } = await twoChats();
    let finish: () => void = () => undefined;
    api.uploadAttachment.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = () => {
            resolve(attachment("a9", "late.txt"));
          };
        }),
    );

    await go("s1", "Fix login");
    await user.upload(screen.getByLabelText("Attach files"), new File(["x"], "late.txt"));
    await go("s2", "Add tests");
    await act(async () => {
      finish();
      await Promise.resolve();
    });
    expect(screen.queryByText("late.txt")).not.toBeInTheDocument();

    await go("s1", "Fix login");
    expect(screen.getByText("late.txt")).toBeInTheDocument();
  });

  it("starts each chat at its latest output, not at another chat's reading position", async () => {
    const { go } = await twoChats();

    await go("s1", "Fix login");
    const box = defined(screen.getByText("Hello from s1").closest<HTMLElement>(".ch-tx"));
    Object.defineProperty(box, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(box, "clientHeight", { configurable: true, value: 300 });
    box.scrollTop = 700;
    fireEvent.scroll(box);
    box.scrollTop = 100;
    fireEvent.scroll(box);
    expect(screen.getByRole("button", { name: "Jump to latest" })).toBeInTheDocument();

    await go("s2", "Add tests");
    expect(screen.queryByRole("button", { name: "Jump to latest" })).not.toBeInTheDocument();
    expect(screen.getByText("Hello from s2").closest(".ch-tx")).not.toBe(box);
  });

  it("keeps a new chat's draft for its project", async () => {
    const { user } = await twoChats();

    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));
    await user.type(screen.getByLabelText("Message"), "An idea");
    await user.click(screen.getByRole("button", { name: /back/i }));
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));

    expect(screen.getByLabelText("Message")).toHaveValue("An idea");
  });
});
