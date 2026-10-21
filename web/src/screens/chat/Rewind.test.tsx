import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { NestEvent, RewindPreview, Session } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { claudeChat, detail, event, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const ACTIONS = "Message actions";
const SHOT = { id: "a1", filename: "shot.png", media_type: "image/png", size: 3 };

const asked = (id: number, text: string) =>
  event({ id, type: "session.user_message", payload: { text, attachments: [] } });

const NO_FILES: RewindPreview = {
  can_rewind: true,
  files_changed: [],
  insertions: 0,
  deletions: 0,
  error: null,
};

const reply = (restore: "code" | "conversation" | "both", text: string | null = "Add zod") => ({
  ...NO_FILES,
  restore,
  text,
  attachments: text === null ? [] : [SHOT],
});

async function openChat(
  chat: Session = session(),
  events: NestEvent[] = [asked(3, "Add zod"), asked(7, "Now the tests")],
  api: FakeApi = fakeApi(),
) {
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) =>
    Promise.resolve((chat.archived_at !== null) === archived ? [chat] : []),
  );
  api.session.mockResolvedValue(detail(chat));
  api.sessionEvents.mockResolvedValue(events);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  if (chat.archived_at !== null) {
    await rendered.user.click(screen.getByRole("button", { name: /^Archived/ }));
  }
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByText("Add zod");
  return { ...rendered, field: screen.getByLabelText("Message") };
}

/** Opens a user message's actions and picks one. */
async function choose(
  user: Awaited<ReturnType<typeof openChat>>["user"],
  item: string,
  message = 0,
) {
  await user.click(defined(screen.getAllByRole("button", { name: ACTIONS })[message]));
  await user.click(screen.getByRole("menuitem", { name: item }));
}

/** Previews by what they restore. */
function previews(api: FakeApi, code: RewindPreview | Error, conversation: RewindPreview) {
  api.rewindPreview.mockImplementation((_, __, restore) =>
    restore === "conversation"
      ? Promise.resolve(conversation)
      : code instanceof Error
        ? Promise.reject(code)
        : Promise.resolve(code),
  );
}

describe("rewinding to before a message (B59)", () => {
  it("restores the conversation and code, then puts the message back in the composer", async () => {
    const { user, api, field, push, container } = await openChat();
    api.rewind.mockResolvedValue(reply("both"));

    await choose(user, "Rewind...");
    const sheet = await screen.findByRole("alertdialog", { name: "Rewind?" });
    expect(api.rewindPreview).toHaveBeenCalledWith("s1", 3, "code");
    expect(api.rewindPreview).toHaveBeenCalledWith("s1", 3, "conversation");
    expect(
      await within(sheet).findByText(
        "2 files go back to how they were before this message (+12 -3): app/form.tsx, app/schema.ts.",
      ),
    ).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Restore conversation and code" }));

    expect(api.rewind).toHaveBeenCalledWith("s1", 3, "both");
    expect(await screen.findByText("Rewound, and the files restored")).toBeInTheDocument();
    expect(field).toHaveValue("Add zod");
    expect(screen.getByRole("button", { name: "Remove shot.png" })).toBeInTheDocument();
    await waitFor(() => {
      expect(field).toHaveFocus();
    });

    push(
      event({
        id: 9,
        type: "session.rewound",
        payload: { message: 3, through: 8, text: "Add zod", attachments: [] },
      }),
    );
    expect(screen.queryByText("Now the tests")).not.toBeInTheDocument();
    expect(defined(container.querySelector(".tx"))).not.toHaveTextContent("Add zod");
  });

  it("restores the conversation only", async () => {
    const { user, api, field } = await openChat();
    api.rewind.mockResolvedValue(reply("conversation"));

    await choose(user, "Rewind...", 1);
    await user.click(await screen.findByRole("button", { name: "Restore conversation" }));

    expect(api.rewind).toHaveBeenCalledWith("s1", 7, "conversation");
    expect(await screen.findByText("Rewound")).toBeInTheDocument();
    expect(field).toHaveValue("Add zod");
  });

  it("restores the code only, leaving the composer alone", async () => {
    const { user, api, field } = await openChat();
    api.rewind.mockResolvedValue(reply("code", null));

    await choose(user, "Rewind...");
    await user.click(await screen.findByRole("button", { name: "Restore code" }));

    expect(api.rewind).toHaveBeenCalledWith("s1", 3, "code");
    expect(await screen.findByText("Files restored")).toBeInTheDocument();
    expect(field).toHaveValue("");
  });

  it("counts the files when only their number is known", async () => {
    const api = fakeApi();
    previews(api, { ...NO_FILES, files_changed: 1, deletions: 4 }, NO_FILES);
    const { user } = await openChat(undefined, undefined, api);

    await choose(user, "Rewind...", 1);

    expect(
      await screen.findByText("1 file goes back to how it was before this message (+0 -4)."),
    ).toBeInTheDocument();
  });

  it("offers no code restore when no file changed", async () => {
    const api = fakeApi();
    previews(api, NO_FILES, NO_FILES);
    const { user } = await openChat(undefined, undefined, api);

    await choose(user, "Rewind...");

    expect(
      await screen.findByText("Nothing to restore. No file changed since this message."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore code" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Restore conversation and code" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Restore conversation" })).toBeEnabled();
  });

  it("says why the code or the conversation cannot be restored", async () => {
    const api = fakeApi();
    previews(
      api,
      { ...NO_FILES, can_rewind: false, error: "No checkpoint for this message" },
      { ...NO_FILES, can_rewind: false, error: null },
    );
    const { user } = await openChat(undefined, undefined, api);

    await choose(user, "Rewind...");
    const sheet = await screen.findByRole("alertdialog", { name: "Rewind?" });

    expect(await within(sheet).findByText("No checkpoint for this message")).toBeInTheDocument();
    expect(
      within(sheet).getByText("The conversation cannot be rewound to before this message."),
    ).toBeInTheDocument();
    for (const name of ["Restore conversation", "Restore code", "Restore conversation and code"]) {
      expect(within(sheet).getByRole("button", { name })).toBeDisabled();
    }
  });

  it("falls back to a general reason for the files", async () => {
    const api = fakeApi();
    previews(api, { ...NO_FILES, can_rewind: false }, NO_FILES);
    const { user } = await openChat(undefined, undefined, api);

    await choose(user, "Rewind...");

    expect(
      await screen.findByText("The files cannot be restored to before this message."),
    ).toBeInTheDocument();
  });

  it("says when a preview or the rewind fails", async () => {
    const api = fakeApi();
    previews(api, new ApiError(500, "engine gone"), NO_FILES);
    api.rewind.mockRejectedValueOnce(new ApiError(409, "The chat is working"));
    const { user, field } = await openChat(undefined, undefined, api);

    await choose(user, "Rewind...");
    expect(await screen.findByText("engine gone")).toBeInTheDocument();
    const sheet = screen.getByRole("alertdialog", { name: "Rewind?" });
    expect(within(sheet).getByText("What would change could not be loaded.")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Restore code" })).toBeDisabled();
    await user.click(within(sheet).getByRole("button", { name: "Restore conversation" }));

    expect(await screen.findByText("The chat is working")).toBeInTheDocument();
    expect(screen.queryByText("Rewound")).not.toBeInTheDocument();
    expect(field).toHaveValue("");
  });

  it("ignores previews that arrive after the sheet closed", async () => {
    const api = fakeApi();
    let finish: (value: RewindPreview) => void = () => undefined;
    api.rewindPreview.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { user } = await openChat(undefined, undefined, api);

    await choose(user, "Rewind...");
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await act(async () => {
      finish(NO_FILES);
      await Promise.resolve();
    });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("asks before replacing what is typed", async () => {
    const { user, api, field } = await openChat();
    api.rewind.mockResolvedValue(reply("conversation"));
    await user.type(field, "Draft");

    await choose(user, "Rewind...");
    await user.click(await screen.findByRole("button", { name: "Restore conversation" }));
    await user.click(await screen.findByRole("button", { name: "Replace" }));

    expect(field).toHaveValue("Add zod");
  });
});

describe("editing a sent message (B59)", () => {
  it("rewinds the conversation to it at once when no file changed since", async () => {
    const api = fakeApi();
    previews(api, NO_FILES, NO_FILES);
    api.rewind.mockResolvedValue(reply("conversation"));
    const { user, field } = await openChat(undefined, undefined, api);

    await choose(user, "Edit");

    expect(api.rewind).toHaveBeenCalledWith("s1", 3, "conversation");
    await waitFor(() => {
      expect(field).toHaveValue("Add zod");
    });
  });

  it("rewinds the conversation at once when the files cannot be checked", async () => {
    const api = fakeApi();
    previews(api, new ApiError(500, "engine gone"), NO_FILES);
    api.rewind.mockResolvedValue(reply("conversation"));
    const { user, field } = await openChat(undefined, undefined, api);

    await choose(user, "Edit");

    await waitFor(() => {
      expect(field).toHaveValue("Add zod");
    });
    // Quiet: the edit itself worked.
    expect(screen.queryByText("engine gone")).not.toBeInTheDocument();
  });

  it("asks whether to restore the code too when files changed since", async () => {
    const { user, api, field } = await openChat();
    api.rewind.mockResolvedValue(reply("both"));

    await choose(user, "Edit", 1);
    const ask = await screen.findByRole("alertdialog", {
      name: "Files changed since this message",
    });
    expect(ask).toHaveTextContent("2 files go back");
    await user.click(within(ask).getByRole("button", { name: "Edit and restore code" }));

    expect(api.rewind).toHaveBeenCalledWith("s1", 7, "both");
    await waitFor(() => {
      expect(field).toHaveValue("Add zod");
    });
  });

  it("can edit the message only, keeping the files", async () => {
    const { user, api } = await openChat();
    api.rewind.mockResolvedValue(reply("conversation"));

    await choose(user, "Edit");
    await user.click(await screen.findByRole("button", { name: "Edit message only" }));

    expect(api.rewind).toHaveBeenCalledWith("s1", 3, "conversation");
  });
});

describe("forking a chat from a message (B59)", () => {
  it("opens the new chat with the message in its composer", async () => {
    const { user, api } = await openChat();
    const forked = session({ id: "s9", title: "Validate contact form (fork)" });
    api.fork.mockResolvedValue({ session: forked, text: "Now the tests", attachments: [SHOT] });
    api.session.mockImplementation((id) =>
      Promise.resolve(detail(id === "s9" ? forked : session())),
    );

    await choose(user, "Fork from here", 1);

    expect(api.fork).toHaveBeenCalledWith("s1", 7);
    expect(
      await screen.findByRole("region", { name: "Validate contact form (fork)" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toHaveValue("Now the tests");
    expect(screen.getByRole("button", { name: "Remove shot.png" })).toBeInTheDocument();
  });

  it("stays when the fork fails", async () => {
    const api = fakeApi();
    api.fork.mockRejectedValueOnce(new ApiError(409, "Claude is working in this chat"));
    const { user } = await openChat(undefined, undefined, api);

    await choose(user, "Fork from here");

    expect(await screen.findByText("Claude is working in this chat")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Validate contact form" })).toBeInTheDocument();
  });
});

describe("message actions", () => {
  it.each(["idle", "interrupted", "failed"] as const)(
    "are offered when no turn runs: %s",
    async (state) => {
      await openChat(session({ state }));

      expect(screen.getAllByRole("button", { name: ACTIONS })).toHaveLength(2);
    },
  );

  it("close without doing anything", async () => {
    const { user, api } = await openChat();

    await user.click(defined(screen.getAllByRole("button", { name: ACTIONS })[0]));
    expect(screen.getAllByRole("menuitem").map((b) => b.textContent)).toEqual([
      "Edit",
      "Rewind...",
      "Fork from here",
    ]);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.rewindPreview).not.toHaveBeenCalled();
  });

  it.each([
    ["while a turn runs", session({ state: "running" })],
    ["while a turn starts", session({ state: "starting" })],
    ["in an archived chat", session({ archived_at: "2026-10-06T11:00:00Z" })],
  ])("are not offered %s", async (_, chat) => {
    await openChat(chat);

    expect(screen.queryByRole("button", { name: ACTIONS })).toBeNull();
  });

  it("are not offered in a Claude Code chat shown read only", async () => {
    const api = fakeApi();
    api.claudeChats.mockResolvedValue([claudeChat()]);
    api.claudeChatEvents.mockResolvedValue([asked(3, "Add zod")]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: /^Tune the hero section/ }));

    await waitFor(() => {
      expect(screen.getByText("Add zod")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: ACTIONS })).toBeNull();
  });
});
