import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { JsonObject, NestEvent } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { detail, event, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const image = (id: string) => ({ attachment_id: id, media_type: "image/png" });

const message = (id: number, blocks: JsonObject[], parent: string | null = null) =>
  event({ id, type: "session.message", payload: { parent_tool_use_id: parent, blocks } });

async function openChat(events: NestEvent[], api: FakeApi = fakeApi()) {
  const chat = session();
  api.repos.mockResolvedValue([repo("cv-page")]);
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
  vi.spyOn(URL, "createObjectURL").mockImplementation(
    (blob) => `blob:${(blob as Blob).type}:${String((blob as Blob).size)}`,
  );
});

describe("images in tool results (B59)", () => {
  it("shows them under the tool's row, fetched once, and opens one full size", async () => {
    const api = fakeApi();
    api.attachment.mockResolvedValue(new Blob(["px"], { type: "image/png" }));
    const { user } = await openChat(
      [
        message(1, [
          { type: "tool_use", id: "t1", name: "Read", input: { file_path: "/w/s1/shot.png" } },
        ]),
        message(2, [
          {
            type: "tool_result",
            tool_use_id: "t1",
            content: "Screenshot taken",
            images: [image("i9")],
          },
        ]),
        message(3, [{ type: "text", text: "Here it is." }]),
        message(4, [{ type: "tool_use", id: "t2", name: "Read", input: { file_path: "/a" } }]),
        message(5, [
          { type: "tool_result", tool_use_id: "t2", content: "", images: [image("i9")] },
        ]),
      ],
      api,
    );

    const thumbs = await screen.findAllByRole("img", { name: "Image from Read" });
    expect(thumbs).toHaveLength(2);
    expect(thumbs[0]).toHaveAttribute("src", "blob:image/png:2");
    expect(api.attachment).toHaveBeenCalledTimes(1);
    expect(api.attachment).toHaveBeenCalledWith("i9");

    await user.click(defined(screen.getAllByRole("button", { name: "Open image" })[0]));
    const sheet = screen.getByRole("dialog", { name: "Image" });
    expect(within(sheet).getByRole("img")).toHaveAttribute("src", "blob:image/png:2");
    await user.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says when an image cannot be loaded, quietly", async () => {
    const api = fakeApi();
    api.attachment.mockRejectedValue(new ApiError(404, "unknown attachment 'gone'"));
    await openChat(
      [
        message(1, [{ type: "tool_use", id: "t1", name: "Shot", input: {} }]),
        message(2, [{ type: "tool_result", tool_use_id: "t1", images: [image("gone")] }]),
      ],
      api,
    );

    expect(await screen.findByText("Image unavailable")).toBeInTheDocument();
    expect(screen.queryByText("unknown attachment 'gone'")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open image" })).toBeNull();
  });

  it("shows a subagent's images in its row", async () => {
    const api = fakeApi();
    api.attachment.mockResolvedValue(new Blob(["abc"], { type: "image/jpeg" }));
    const { user } = await openChat(
      [
        message(1, [{ type: "tool_use", id: "t1", name: "Agent", input: { description: "Look" } }]),
        message(
          2,
          [{ type: "tool_result", tool_use_id: "x", content: "Shot", images: [image("s1")] }],
          "t1",
        ),
      ],
      api,
    );

    await user.click(screen.getByText("Agent"));

    expect(await screen.findByRole("img", { name: "Image from a subagent" })).toHaveAttribute(
      "src",
      "blob:image/jpeg:3",
    );
  });
});
