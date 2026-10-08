/// <reference types="node" />
import { readFileSync } from "node:fs";
import { screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { fakeApi } from "../test/fakeApi.ts";
import { detail, queuedMessage, repo, session } from "../test/fixtures.ts";
import { renderApp } from "../test/render.tsx";

// The app's own stylesheets: jsdom has no layout, but it applies their declared sizes.
const SHEETS = ["base.css", "screens.css", "chat.css"].map((name) =>
  readFileSync(`src/styles/${name}`, "utf8"),
);

const styles = SHEETS.map((text) => {
  const style = document.createElement("style");
  style.textContent = text;
  return style;
});

beforeAll(() => {
  document.head.append(...styles);
});

afterAll(() => {
  for (const style of styles) style.remove();
});

/** The box a control declares, in CSS pixels. */
function box(element: HTMLElement) {
  const css = getComputedStyle(element);
  const px = (value: string) => Number.parseFloat(value) || 0;
  return {
    width: Math.max(px(css.width), px(css.minWidth)),
    height: Math.max(px(css.height), px(css.minHeight)),
  };
}

// Apple's smallest comfortable tap target.
const TAP = 44;

describe("tap targets", () => {
  it("are at least 44 points in a chat", async () => {
    const chat = session({ state: "running" });
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("todo-ui")]);
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
    api.session.mockResolvedValue(
      detail({
        ...chat,
        queued: [queuedMessage()],
        background: {
          running: 1,
          completed: 0,
          items: [
            {
              id: "t1",
              kind: "bash",
              name: "npm run dev",
              description: null,
              status: "running",
              started_at: null,
              finished_at: null,
            },
          ],
        },
      }),
    );
    api.uploadAttachment.mockResolvedValue({
      id: "a1",
      filename: "shot.png",
      media_type: "image/png",
      size: 3,
      created_at: "x",
    });
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));
    await user.upload(screen.getByLabelText("Attach files"), new File(["x"], "shot.png"));
    await user.type(screen.getByLabelText("Message"), "Next");

    const controls = [
      await screen.findByRole("button", { name: "Remove shot.png" }),
      await screen.findByRole("button", { name: "Cancel queued message" }),
      screen.getByRole("button", { name: "Queue" }),
    ];
    for (const control of controls) {
      expect(box(control), control.getAttribute("aria-label") ?? "").toEqual({
        width: TAP,
        height: TAP,
      });
    }
    // The background bar spans the column; its height is what counts.
    expect(box(screen.getByRole("button", { name: "1 running task" })).height).toBe(TAP);
  });

  it("are at least 44 points in the search field", async () => {
    const { user } = await renderApp();
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.type(screen.getByRole("searchbox"), "form");

    expect(box(screen.getByRole("button", { name: "Clear search" }))).toEqual({
      width: TAP,
      height: TAP,
    });
  });
});
