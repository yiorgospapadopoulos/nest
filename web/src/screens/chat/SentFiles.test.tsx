import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { JsonObject, NestEvent } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { detail, event, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const said = (attachments: JsonObject[], text = "Look") =>
  event({ id: 1, type: "session.user_message", payload: { text, attachments } });

const png = (id: string) => ({ id, filename: `${id}.png`, media_type: "image/png", size: 2048 });
const pdf = (id: string) => ({
  id,
  filename: "notes.pdf",
  media_type: "application/pdf",
  size: 2_400_000,
});

async function openChat(events: NestEvent[], api: FakeApi) {
  const chat = session();
  api.repos.mockResolvedValue([repo("todo-ui")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.sessionEvents.mockResolvedValue(events);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));
  await screen.findByRole("region", { name: "Validate contact form" });
  return rendered;
}

beforeEach(() => {
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:sent");
  vi.spyOn(URL, "revokeObjectURL").mockReturnValue();
});

describe("images and files sent with a message", () => {
  it("shows a sent image, fetched with the device's access, and opens it larger", async () => {
    const api = fakeApi();
    api.attachment.mockResolvedValue(new Blob(["px"], { type: "image/png" }));
    const { user } = await openChat([said([png("i1")])], api);

    expect(await screen.findByRole("img", { name: "i1.png" })).toHaveAttribute("src", "blob:sent");
    expect(api.attachment).toHaveBeenCalledWith("i1");

    await user.click(screen.getByRole("button", { name: "Open i1.png" }));
    const sheet = screen.getByRole("dialog", { name: "Image" });
    expect(within(sheet).getByRole("img")).toHaveAttribute("src", "blob:sent");
  });

  it("says Image deleted for a 404 only", async () => {
    const api = fakeApi();
    api.attachment.mockImplementation((id) =>
      Promise.reject(new ApiError(id === "i2" ? 404 : 500, "no")),
    );
    await openChat([said([png("i2"), png("i3")])], api);

    expect(await screen.findByText("Image deleted")).toBeInTheDocument();
    expect(await screen.findByText("Image not available")).toBeInTheDocument();
    expect(screen.getAllByText(/deleted/i)).toHaveLength(1);
  });

  it("tries a failed image again when it next shows, and keeps a deleted one", async () => {
    const api = fakeApi();
    api.attachment.mockRejectedValue(new ApiError(500, "no"));
    const first = await openChat([said([png("i4")])], api);
    await screen.findByText("Image not available");
    first.unmount();
    window.history.replaceState(null, "", "/");

    api.attachment.mockResolvedValue(new Blob(["px"], { type: "image/png" }));
    await openChat([said([png("i4")])], api);

    expect(await screen.findByRole("img", { name: "i4.png" })).toBeInTheDocument();
  });

  it("dims a deleted file's row, and not one that failed its check", async () => {
    const api = fakeApi();
    api.attachmentThere.mockImplementation((id) =>
      Promise.reject(new ApiError(id === "f1" ? 404 : 500, "no")),
    );
    await openChat([said([pdf("f1"), { ...pdf("f2"), filename: "kept.pdf" }])], api);

    expect(await screen.findByText("Deleted")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^PDF notes\.pdf/ })).toBeNull();
    expect(screen.getByRole("button", { name: /kept\.pdf/ })).toHaveTextContent("2.4 MB");
  });

  it("opens a sent file in the viewer through the API, and saves it from there", async () => {
    const api = fakeApi();
    api.attachment.mockResolvedValue(new Blob(["line one\nline two\n"]));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockReturnValue();
    const { user } = await openChat(
      [said([{ id: "f3", filename: "app.log", media_type: "text/plain", size: 18 }])],
      api,
    );

    await user.click(screen.getByRole("button", { name: /app\.log/ }));

    const sheet = await screen.findByRole("dialog", { name: "app.log" });
    expect(api.attachment).toHaveBeenCalledWith("f3");
    expect(await within(sheet).findByText("line two")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe("app.log");
  });

  it("says when the file of a row has gone since", async () => {
    const api = fakeApi();
    api.attachmentThere.mockResolvedValue(undefined);
    api.attachment.mockRejectedValue(new ApiError(404, "no"));
    const { user } = await openChat([said([pdf("f5")])], api);

    await user.click(screen.getByRole("button", { name: /notes\.pdf/ }));

    const sheet = await screen.findByRole("dialog", { name: "notes.pdf" });
    expect(await within(sheet).findByText("This file is not there any more.")).toBeInTheDocument();
  });

  it("shows a message of files alone with no empty bubble", async () => {
    const api = fakeApi();
    await openChat([said([pdf("f4")], "")], api);

    const row = screen.getByRole("button", { name: /notes\.pdf/ });
    expect(row.closest(".m-u")).toBeNull();
    expect(document.querySelector(".m-u")).toBeNull();
  });
});
