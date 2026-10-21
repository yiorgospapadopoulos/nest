import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Attachment, Session } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { detail, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

async function openChat(chat: Session = session()) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.uploadAttachment.mockImplementation((file) =>
    Promise.resolve(uploaded(file.name === "image.png" ? "a1" : `id-${file.name}`, file)),
  );
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  return rendered;
}

const uploaded = (id: string, file: File): Attachment => ({
  id,
  filename: file.name,
  media_type: file.type,
  size: file.size,
  created_at: "x",
});

const png = () => new File(["px"], "image.png", { type: "image/png" });

/** Object URLs of the thumbnails, which Node makes only of its own blobs. */
function objectUrls() {
  vi.spyOn(URL, "createObjectURL").mockImplementation(
    (blob) => `blob:${blob instanceof File ? blob.name : "x"}`,
  );
  return vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
}

let revoked: ReturnType<typeof objectUrls>;

beforeEach(() => {
  revoked = objectUrls();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("pasting and dropping into the composer (B59)", () => {
  it("attaches a pasted image as a thumbnail that can be removed", async () => {
    const { api } = await openChat();
    const field = screen.getByLabelText("Message");

    fireEvent.paste(field, { clipboardData: { files: [png()], items: [] } });

    const list = await screen.findByRole("list", { name: "Attachments" });
    const thumb = await within(list).findByRole("img", { name: "image.png" });
    expect(thumb).toHaveAttribute("src", "blob:image.png");
    expect(api.uploadAttachment).toHaveBeenCalledWith(
      expect.objectContaining({ name: "image.png" }),
    );
    fireEvent.click(within(list).getByRole("button", { name: "Remove image.png" }));
    expect(screen.queryByRole("list", { name: "Attachments" })).not.toBeInTheDocument();
    expect(revoked).toHaveBeenCalledWith("blob:image.png");
  });

  it("takes a pasted image from the clipboard's items, as Safari on iPhone has it", async () => {
    const { api, user } = await openChat();
    const field = screen.getByLabelText("Message");
    const image = png();

    fireEvent.paste(field, {
      clipboardData: {
        files: [],
        items: [
          { kind: "string", getAsFile: () => null },
          { kind: "file", getAsFile: () => null },
          { kind: "file", getAsFile: () => image },
        ],
      },
    });
    await screen.findByRole("img", { name: "image.png" });
    await user.type(field, "Look");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(api.sendMessage).toHaveBeenCalledWith("s1", "Look", ["a1"]);
    await waitFor(() => {
      expect(screen.queryByRole("img", { name: "image.png" })).not.toBeInTheDocument();
    });
  });

  it("leaves pasted text alone", async () => {
    const { api } = await openChat();
    const field = screen.getByLabelText("Message");
    const pasted = fireEvent.paste(field, { clipboardData: { files: [], items: [] } });
    expect(pasted).toBe(true);
    expect(api.uploadAttachment).not.toHaveBeenCalled();
  });

  it("attaches dropped files, images as thumbnails and others by name", async () => {
    const { api } = await openChat();
    const composer = defined(screen.getByLabelText("Message").closest(".comp"));
    const notes = new File(["x"], "notes.txt", { type: "text/plain" });

    // Text being dragged is not taken.
    expect(fireEvent.dragOver(composer, { dataTransfer: { types: ["text/plain"] } })).toBe(true);
    expect(fireEvent.dragOver(composer, { dataTransfer: { types: ["Files"] } })).toBe(false);
    fireEvent.drop(composer, { dataTransfer: { types: ["Files"], files: [png(), notes] } });

    const list = await screen.findByRole("list", { name: "Attachments" });
    await within(list).findByText("notes.txt");
    expect(await within(list).findByRole("img", { name: "image.png" })).toBeInTheDocument();
    expect(within(list).getAllByRole("img")).toHaveLength(1);
    expect(api.uploadAttachment).toHaveBeenCalledTimes(2);
  });

  it("takes no files in a closed chat", async () => {
    const { api } = await openChat(session({ state: "closed" }));
    const field = screen.getByLabelText("Message");
    const composer = defined(field.closest(".comp"));
    expect(fireEvent.paste(field, { clipboardData: { files: [png()], items: [] } })).toBe(true);
    expect(fireEvent.dragOver(composer, { dataTransfer: { types: ["Files"] } })).toBe(true);
    fireEvent.drop(composer, { dataTransfer: { types: ["Files"], files: [png()] } });
    expect(api.uploadAttachment).not.toHaveBeenCalled();
  });
});
