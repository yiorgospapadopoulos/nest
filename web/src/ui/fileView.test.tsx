import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client.ts";
import { fakeApi, type FakeApi } from "../test/fakeApi.ts";
import { detail, event, repo, session } from "../test/fixtures.ts";
import { renderApp } from "../test/render.tsx";
import { kindOf } from "./fileKind.ts";

const reply = (text: string) =>
  event({
    id: 1,
    type: "session.message",
    payload: { parent_tool_use_id: null, blocks: [{ type: "text", text }] },
  });

async function openChat(text: string, api: FakeApi) {
  const chat = session();
  api.repos.mockResolvedValue([repo("todo-ui")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.sessionEvents.mockResolvedValue([reply(text)]);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));
  await screen.findByRole("region", { name: "Validate contact form" });
  return { ...rendered, chat };
}

describe("files a reply names, on the phone (B144)", () => {
  it("open in the viewer from the chat's folder, at the line named", async () => {
    const api = fakeApi();
    const code = Array.from({ length: 30 }, (_, index) => `line ${String(index + 1)}`).join("\n");
    api.namedFile.mockResolvedValue(new Blob([code]));
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    const { user, chat } = await openChat("The limit is in `src/store.py:19`.", api);

    await user.click(await screen.findByRole("link", { name: "src/store.py:19" }));

    const sheet = await screen.findByRole("dialog", { name: "store.py" });
    expect(api.namedFile).toHaveBeenCalledWith(chat.id, "src/store.py");
    await waitFor(() => {
      expect(sheet.querySelectorAll(".fv-ln")).toHaveLength(30);
    });
    // The number is coloured as code, so the line is split into spans.
    expect(sheet.querySelector(".fv-on")?.textContent).toBe("19line 19\n");
    expect(scrolled).toHaveBeenCalled();
  });

  it("say so when the file is not in the chat's folder", async () => {
    const api = fakeApi();
    api.namedFile.mockRejectedValue(new ApiError(404, "file not found"));
    const { user } = await openChat("See `../secret.txt`.", api);

    await user.click(await screen.findByRole("link", { name: "../secret.txt" }));

    const sheet = await screen.findByRole("dialog", { name: "secret.txt" });
    expect(await within(sheet).findByText("This file is not there any more.")).toBeInTheDocument();
  });
});

describe("the kind a file shows as", () => {
  it.each([
    ["app.ts", "video/mp2t", "export const a = 1;", "text"],
    ["clip.mov", "video/quicktime", "\u0000\u0001", "video"],
    ["report.pdf", "", "%PDF-1.7", "pdf"],
    ["notes", "", "plain words", "text"],
    ["blob.bin", "application/octet-stream", "\u0000\u0001\u0002", "other"],
    ["page.svg", "image/svg+xml", "<svg/>", "text"],
  ])("%s (%s) shows as %s", async (name, type, content, kind) => {
    expect(await kindOf(name, type, new Blob([content]))).toBe(kind);
  });
});
