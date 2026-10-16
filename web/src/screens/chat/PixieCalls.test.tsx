import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { JsonObject } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { detail, event, pixie, repo, session, team } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const tester = pixie({ id: "p1", slug: "tester", name: "Tester", mascot: "owl" });
const message = (id: number, parent: string | null, ...blocks: JsonObject[]) =>
  event({ id, type: "session.message", payload: { parent_tool_use_id: parent, blocks } });
const callTester = (id: string) => ({
  type: "tool_use",
  id,
  name: "Task",
  input: { description: "Check the form", subagent_type: "tester" },
});

async function openChat(
  events: ReturnType<typeof event>[],
  state: "idle" | "running" = "idle",
  api = fakeApi(),
) {
  const chat = session({ state });
  api.pixies.mockResolvedValue([tester]);
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.sessionEvents.mockResolvedValue(events);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  return rendered;
}

describe("pixie calls in the chat", () => {
  it("shows the call as the pixie's row, opening in place to its own messages", async () => {
    const { user } = await openChat([
      message(1, null, callTester("a1")),
      message(2, "a1", { type: "text", text: "Looking at the form." }),
      message(3, "a1", { type: "tool_use", id: "s1", name: "Read", input: { file_path: "f.ts" } }),
      message(4, null, { type: "tool_result", tool_use_id: "a1", content: "All good" }),
    ]);

    const row = await screen.findByRole("button", { name: /Check the form/ });
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Looking at the form.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Tester" })).toBeInTheDocument();

    await user.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    const steps = screen.getByRole("group", { name: "Tester's steps" });
    expect(within(steps).getByText("Looking at the form.")).toBeInTheDocument();
    expect(within(steps).getByText("Read f.ts")).toHaveClass("pxstep");
    expect(within(steps).getByText("All good")).toBeInTheDocument();

    await user.click(row);
    expect(screen.queryByRole("group", { name: "Tester's steps" })).not.toBeInTheDocument();
  });

  it("goes to the pixie's page from its mascot or name", async () => {
    const { user } = await openChat([message(1, null, callTester("a1"))], "running");

    expect(await screen.findByRole("button", { name: /Check the form/ })).toHaveTextContent(
      "running",
    );
    await user.click(screen.getByRole("button", { name: /Check the form/ }));
    expect(screen.getByRole("group", { name: "Tester's steps" })).toHaveTextContent("running");

    await user.click(screen.getByRole("button", { name: "Open Tester" }));
    expect(await screen.findByRole("tab", { name: "Chat", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Tester/ })).toBeInTheDocument();
  });

  it("shows a failed call, and one the turn stopped", async () => {
    const { user } = await openChat([
      message(1, null, callTester("a1")),
      message(2, null, { type: "tool_result", tool_use_id: "a1", content: "", is_error: true }),
      message(3, null, { type: "text", text: "Trying again." }),
      message(4, null, callTester("a2")),
      event({ id: 5, type: "session.state", payload: { state: "interrupted" } }),
    ]);

    const [failed, stopped] = await screen.findAllByRole("button", { name: /Check the form/ });
    expect(failed).toHaveTextContent("failed");
    expect(within(defined(failed)).getByText("failed")).toHaveClass("bad");
    await user.click(defined(stopped));
    expect(screen.getByRole("group", { name: "Tester's steps" })).toHaveTextContent("stopped");
  });

  it("draws known mentions in sent messages in the pixie's colour", async () => {
    const api = fakeApi();
    api.teams.mockResolvedValue([
      team({ id: "qa", handle: "qa", leader_id: "p1" }),
      team({ id: "x", handle: "nobody-leads", leader_id: null }),
    ]);
    await openChat(
      [
        event({
          id: 1,
          type: "session.user_message",
          payload: { text: "Ask @tester, then @qa and @nobody-leads or @stranger" },
        }),
      ],
      "idle",
      api,
    );

    const slug = await screen.findByText("@tester", { selector: ".m-u span" });
    expect(slug).toHaveClass("mention");
    expect(slug.style.getPropertyValue("--px")).toBe(tester.color);
    expect(screen.getByText("@qa", { selector: ".m-u span" }).style.getPropertyValue("--px")).toBe(
      tester.color,
    );
    // The bubble still reads as the message typed.
    expect(slug.closest(".m-u")).toHaveTextContent(
      "Ask @tester, then @qa and @nobody-leads or @stranger",
    );
    expect(screen.getByText(/and @nobody-leads or @stranger/, { selector: ".m-u" })).toBeVisible();
    expect(screen.queryByText("@stranger", { selector: ".m-u span" })).not.toBeInTheDocument();
  });
});

describe("a pixie call's sprite (B48)", () => {
  it("hops while the call runs, and rests once it answered", async () => {
    const { push } = await openChat([message(1, null, callTester("a1"))], "running");
    const sprite = () =>
      defined(screen.getByRole("button", { name: "Open Tester" }).querySelector("svg"));
    expect(sprite()).toHaveClass("pxwork");

    push(message(2, null, { type: "tool_result", tool_use_id: "a1", content: "All good" }));
    expect(await screen.findByText("All good")).toBeInTheDocument();
    expect(sprite()).not.toHaveClass("pxwork");
  });
});
