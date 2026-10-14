import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { NestEvent, Session } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { claudeChat, detail, event, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const RESTORE = "Restore files to before this message";

const asked = (id: number, text: string) =>
  event({ id, type: "session.user_message", payload: { text, attachments: [] } });

async function openChat(
  chat: Session = session(),
  events: NestEvent[] = [asked(3, "Add zod"), asked(7, "Now the tests")],
  api: FakeApi = fakeApi(),
) {
  api.repos.mockResolvedValue([repo("todo-ui")]);
  api.sessions.mockImplementation((archived) =>
    Promise.resolve((chat.archived_at !== null) === archived ? [chat] : []),
  );
  api.session.mockResolvedValue(detail(chat));
  api.sessionEvents.mockResolvedValue(events);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  if (chat.archived_at !== null) {
    await rendered.user.click(screen.getByRole("button", { name: /^Archived/ }));
  }
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByText("Add zod");
  return rendered;
}

describe("restoring files to before a message", () => {
  it("shows what changes back, then restores only the files", async () => {
    const { user, api } = await openChat();
    const buttons = screen.getAllByRole("button", { name: RESTORE });
    expect(buttons).toHaveLength(2);

    await user.click(defined(buttons[0]));
    const sheet = await screen.findByRole("alertdialog", { name: "Restore files?" });
    expect(api.rewindPreview).toHaveBeenCalledWith("s1", 3);
    expect(
      await within(sheet).findByText(
        "2 files go back to how they were before this message (+12 -3): app/form.tsx, app/schema.ts.",
      ),
    ).toBeInTheDocument();
    expect(sheet).toHaveTextContent(
      "Only files are restored. The conversation stays as it is, and Claude is not told.",
    );
    await user.click(within(sheet).getByRole("button", { name: "Restore files" }));

    expect(api.rewind).toHaveBeenCalledWith("s1", 3);
    expect(await screen.findByText("Files restored")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("counts the files when only their number is known", async () => {
    const api = fakeApi();
    api.rewindPreview.mockResolvedValue({
      can_rewind: true,
      files_changed: 1,
      insertions: 0,
      deletions: 4,
      error: null,
    });
    const { user } = await openChat(undefined, undefined, api);

    await user.click(defined(screen.getAllByRole("button", { name: RESTORE })[1]));

    expect(
      await screen.findByText("1 file goes back to how it was before this message (+0 -4)."),
    ).toBeInTheDocument();
    expect(api.rewindPreview).toHaveBeenCalledWith("s1", 7);
  });

  it("says when nothing would change", async () => {
    const api = fakeApi();
    api.rewindPreview.mockResolvedValue({
      can_rewind: true,
      files_changed: [],
      insertions: 0,
      deletions: 0,
      error: null,
    });
    const { user } = await openChat(undefined, undefined, api);

    await user.click(defined(screen.getAllByRole("button", { name: RESTORE })[0]));

    expect(
      await screen.findByText(/Nothing to restore\. No file changed since this message\./),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore files" })).toBeDisabled();
  });

  it("says why the files cannot be restored", async () => {
    const api = fakeApi();
    api.rewindPreview.mockResolvedValue({
      can_rewind: false,
      files_changed: [],
      insertions: 0,
      deletions: 0,
      error: "No checkpoint for this message",
    });
    const { user } = await openChat(undefined, undefined, api);

    await user.click(defined(screen.getAllByRole("button", { name: RESTORE })[0]));
    const sheet = await screen.findByRole("alertdialog", { name: "Restore files?" });

    expect(await within(sheet).findByText("No checkpoint for this message")).toBeInTheDocument();
    expect(within(sheet).queryByRole("button", { name: "Restore files" })).toBeNull();
  });

  it("falls back to a general reason when the Mac gives none", async () => {
    const api = fakeApi();
    api.rewindPreview.mockResolvedValue({
      can_rewind: false,
      files_changed: [],
      insertions: 0,
      deletions: 0,
      error: null,
    });
    const { user } = await openChat(undefined, undefined, api);

    await user.click(defined(screen.getAllByRole("button", { name: RESTORE })[0]));

    expect(
      await screen.findByText("The files cannot be restored to before this message."),
    ).toBeInTheDocument();
  });

  it("says when the preview or the restore fails", async () => {
    const api = fakeApi();
    api.rewindPreview.mockRejectedValueOnce(new ApiError(500, "engine gone"));
    api.rewind.mockRejectedValueOnce(new ApiError(409, "The chat is working"));
    const { user } = await openChat(undefined, undefined, api);
    const first = () => defined(screen.getAllByRole("button", { name: RESTORE })[0]);

    await user.click(first());
    expect(await screen.findByText("engine gone")).toBeInTheDocument();
    const sheet = screen.getByRole("alertdialog", { name: "Restore files?" });
    expect(within(sheet).getByText("What would change could not be loaded.")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Cancel" }));

    await user.click(first());
    await user.click(await screen.findByRole("button", { name: "Restore files" }));
    expect(await screen.findByText("The chat is working")).toBeInTheDocument();
    expect(screen.queryByText("Files restored")).not.toBeInTheDocument();
  });

  it("ignores a preview that arrives after the question closed", async () => {
    const api = fakeApi();
    let finish: (value: Awaited<ReturnType<FakeApi["rewindPreview"]>>) => void = () => undefined;
    api.rewindPreview.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { user } = await openChat(undefined, undefined, api);

    await user.click(defined(screen.getAllByRole("button", { name: RESTORE })[0]));
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await act(async () => {
      finish({ can_rewind: true, files_changed: 2, insertions: 1, deletions: 1, error: null });
      await Promise.resolve();
    });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it.each(["idle", "interrupted", "failed"] as const)(
    "is offered when no turn runs: %s",
    async (state) => {
      await openChat(session({ state }));

      expect(screen.getAllByRole("button", { name: RESTORE })).toHaveLength(2);
    },
  );

  it.each([
    ["while a turn runs", session({ state: "running" })],
    ["while a turn starts", session({ state: "starting" })],
    ["in an archived chat", session({ archived_at: "2026-10-06T11:00:00Z" })],
  ])("is not offered %s", async (_, chat) => {
    await openChat(chat);

    expect(screen.queryByRole("button", { name: RESTORE })).toBeNull();
  });

  it("is not offered in a Claude Code chat shown read only", async () => {
    const api = fakeApi();
    api.claudeChats.mockResolvedValue([claudeChat()]);
    api.claudeChatEvents.mockResolvedValue([asked(3, "Add zod")]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: /^Tune the hero section/ }));

    await waitFor(() => {
      expect(screen.getByText("Add zod")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: RESTORE })).toBeNull();
  });
});
