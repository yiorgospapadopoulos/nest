import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fakeApi } from "../test/fakeApi.ts";
import { detail, repo, session } from "../test/fixtures.ts";
import { memoryStorage, renderApp } from "../test/render.tsx";
import { DRAFTS_KEY, loadDrafts, saveDrafts } from "./devicePrefs.ts";

const attachment = {
  id: "a1",
  filename: "shot.png",
  media_type: "image/png",
  size: 3,
  created_at: "x",
};

function chatApi() {
  const api = fakeApi();
  const chat = session();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.uploadAttachment.mockResolvedValue(attachment);
  return api;
}

async function openChat(storage: Storage) {
  const rendered = await renderApp({ api: chatApi(), storage });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));
  await screen.findByRole("region", { name: "Validate contact form" });
  return rendered;
}

describe("saved drafts", () => {
  it("keep a chat's message and attachments when the app is opened again", async () => {
    const storage = memoryStorage();
    const first = await openChat(storage);
    await first.user.type(screen.getByLabelText("Message"), "Half a thought");
    await first.user.upload(screen.getByLabelText("Attach files"), new File(["x"], "shot.png"));
    await screen.findByRole("button", { name: "Remove shot.png" });
    first.unmount();
    // Opened again from the Home Screen, at its start page.
    window.history.replaceState(null, "", "/");

    await openChat(storage);

    expect(screen.getByLabelText("Message")).toHaveValue("Half a thought");
    expect(screen.getByRole("button", { name: "Remove shot.png" })).toBeInTheDocument();
  });

  it("are forgotten for chats and projects removed while the app was closed", async () => {
    const storage = memoryStorage();
    const draft = { text: "x", files: [] };
    saveDrafts(() => storage, {
      "session:s1": draft,
      "session:deleted": draft,
      "new:cv-page": draft,
      "new:removed": draft,
    });

    await renderApp({ api: chatApi(), storage });

    await waitFor(() => {
      expect(Object.keys(loadDrafts(() => storage))).toEqual(["session:s1", "new:cv-page"]);
    });
  });

  it("are forgotten once the message is sent", async () => {
    const storage = memoryStorage();
    const { user } = await openChat(storage);

    await user.type(screen.getByLabelText("Message"), "Ship it{Enter}");

    await waitFor(() => {
      expect(loadDrafts(() => storage)).toEqual({});
    });
  });

  it("read only well-formed drafts", () => {
    const storage = memoryStorage();
    storage.setItem(
      DRAFTS_KEY,
      JSON.stringify({
        "session:s1": { text: "kept", files: [attachment, { id: 4 }, null] },
        "session:s2": { text: 5 },
        "new:cv-page": { text: "", files: [] },
        "session:s3": "nope",
      }),
    );

    expect(loadDrafts(() => storage)).toEqual({
      "session:s1": { text: "kept", files: [attachment] },
    });
    storage.setItem(DRAFTS_KEY, "[1]");
    expect(loadDrafts(() => storage)).toEqual({});
    storage.setItem(DRAFTS_KEY, "{broken");
    expect(loadDrafts(() => storage)).toEqual({});
  });

  it("work without storage, for as long as the app is open", async () => {
    const blocked = () => {
      throw new Error("blocked");
    };
    const storage = { getItem: blocked, setItem: blocked } as unknown as Storage;

    expect(loadDrafts(() => storage)).toEqual({});
    expect(() => {
      saveDrafts(() => storage, { "session:s1": { text: "x", files: [] } });
    }).not.toThrow();
    const { user } = await openChat(storage);
    await user.type(screen.getByLabelText("Message"), "Still here");
    expect(screen.getByLabelText("Message")).toHaveValue("Still here");
  });
});
