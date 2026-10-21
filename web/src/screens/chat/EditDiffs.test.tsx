import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { JsonObject, NestEvent } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { detail, event, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

async function openChat(events: NestEvent[]) {
  const chat = session({ state: "idle" });
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.sessionEvents.mockResolvedValue(events);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  return rendered;
}

const message = (id: number, ...blocks: JsonObject[]) =>
  event({ id, type: "session.message", payload: { parent_tool_use_id: null, blocks } });
const use = (id: string, name: string, input: JsonObject) => ({
  type: "tool_use",
  id,
  name,
  input,
});
const result = (id: string, content: string, failed = false) => ({
  type: "tool_result",
  tool_use_id: id,
  content,
  is_error: failed,
});

// The diff's lines as signs and text, as they read.
const lines = (diff: HTMLElement) =>
  [...diff.querySelectorAll(".dl")].map((line) => line.textContent);

describe("edit diffs in the transcript (B59)", () => {
  it("shows an edit's changes inline with the file and counts", async () => {
    await openChat([
      message(
        1,
        use("e1", "Edit", {
          file_path: "/w/s1/app/page.tsx",
          old_string: "const a = 1;\nconst b = 2;",
          new_string: "const a = 1;\nconst b = 3;",
        }),
      ),
      message(2, result("e1", "The file has been updated.")),
    ]);

    const diff = await screen.findByRole("group", { name: "Changes to app/page.tsx" });
    expect(lines(diff)).toEqual([" const a = 1;", "-const b = 2;", "+const b = 3;"]);
    const row = defined(diff.closest<HTMLElement>(".tool"));
    expect(within(row).getByText("Edit")).toBeInTheDocument();
    expect(within(row).getByText("app/page.tsx")).toBeInTheDocument();
    expect(within(row).getByLabelText("1 added, 1 removed")).toHaveTextContent("+1 -1");
    // A plain success says nothing more; the tool's own message stays out.
    expect(within(row).queryByText("The file has been updated.")).toBeNull();
  });

  it("folds a long diff to its first lines, and shows all of it on request", async () => {
    const content = Array.from({ length: 20 }, (_, i) => `line ${String(i + 1)}`).join("\n");
    const { user } = await openChat([
      message(1, use("w1", "Write", { file_path: "/w/s1/notes.md", content })),
      message(2, result("w1", "File created")),
    ]);

    const diff = await screen.findByRole("group", { name: "Changes to notes.md" });
    expect(lines(diff)).toHaveLength(8);
    expect(screen.getByLabelText("20 added, 0 removed")).toHaveTextContent("+20 -0");

    await user.click(screen.getByRole("button", { name: "Show all 20 lines" }));
    expect(lines(diff)).toHaveLength(20);

    await user.click(screen.getByRole("button", { name: "Show less" }));
    expect(lines(diff)).toHaveLength(8);
  });

  it("shows a MultiEdit's edits apart", async () => {
    await openChat([
      message(
        1,
        use("m1", "MultiEdit", {
          file_path: "/w/s1/a.css",
          edits: [
            { old_string: "a", new_string: "b" },
            { old_string: "c", new_string: "d" },
          ],
        }),
      ),
    ]);

    const diff = await screen.findByRole("group", { name: "Changes to a.css" });
    expect(lines(diff)).toEqual(["-a", "+b", "…", "-c", "+d"]);
    // Its turn has not ended, so it still runs.
    expect(
      within(defined(diff.closest<HTMLElement>(".tool"))).getByText("running"),
    ).toBeInTheDocument();
  });

  it("marks a failed edit and shows why", async () => {
    await openChat([
      message(1, use("e1", "Edit", { file_path: "/w/s1/a.ts", old_string: "x", new_string: "y" })),
      message(2, result("e1", "String to replace not found", true)),
    ]);

    const diff = await screen.findByRole("group", { name: "Changes to a.ts" });
    const row = defined(diff.closest<HTMLElement>(".tool"));
    expect(within(row).getByText("failed")).toHaveClass("bad");
    expect(within(row).getByText("String to replace not found")).toBeInTheDocument();
  });
});
