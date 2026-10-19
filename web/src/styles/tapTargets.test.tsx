/// <reference types="node" />
import { readFileSync } from "node:fs";
import { screen, within } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { fakeApi } from "../test/fakeApi.ts";
import {
  detail,
  groupEntry,
  pixie,
  queuedMessage,
  repo,
  review,
  session,
  team,
} from "../test/fixtures.ts";
import { openPixie } from "../test/pixies.ts";
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

/**
 * What a tap reaches: the control's box, or the larger hit area a ::before of its own
 * declares (jsdom has no pseudo-element styles, so the rule is read from the sheet).
 */
function hitBox(element: HTMLElement) {
  const own = box(element);
  const px = (value: string) => Number.parseFloat(value) || 0;
  let width = own.width;
  let height = own.height;
  for (const sheet of document.styleSheets) {
    for (const rule of sheet.cssRules) {
      if (!(rule instanceof CSSStyleRule) || !rule.selectorText.endsWith("::before")) continue;
      if (!element.matches(rule.selectorText.replace(/::before$/, ""))) continue;
      width = Math.max(width, px(rule.style.width), px(rule.style.minWidth));
      height = Math.max(height, px(rule.style.height), px(rule.style.minHeight));
    }
  }
  return { width, height };
}

// Apple's smallest comfortable tap target.
const TAP = 44;

describe("tap targets", () => {
  it("are at least 44 points in a chat", async () => {
    const chat = session({ state: "running" });
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("cv-page")]);
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
      await screen.findByRole("button", { name: "Remove pending message" }),
      screen.getByRole("button", { name: "Edit pending message" }),
      screen.getByRole("button", { name: "Send" }),
    ];
    for (const control of controls) {
      expect(box(control), control.getAttribute("aria-label") ?? "").toEqual({
        width: TAP,
        height: TAP,
      });
    }
    // A text button: its height is what counts.
    expect(box(screen.getByRole("button", { name: "Send now" })).height).toBe(TAP);
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

  it("are at least 44 points in the pixie list and a pixie call", async () => {
    const tester = pixie({ team_id: "t1" });
    const chat = session();
    const api = fakeApi();
    api.pixies.mockResolvedValue([tester]);
    api.teams.mockResolvedValue([team({ leader_id: tester.id })]);
    api.repos.mockResolvedValue([repo("cv-page")]);
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
    api.session.mockResolvedValue(detail(chat));
    api.sessionEvents.mockResolvedValue([
      {
        id: 1,
        session_id: chat.id,
        type: "session.message",
        ts: "x",
        payload: {
          parent_tool_use_id: null,
          blocks: [
            { type: "tool_use", id: "a1", name: "Task", input: { subagent_type: "tester" } },
          ],
        },
      },
    ]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));

    const controls = [
      screen.getByRole("button", { name: "New team" }),
      screen.getByRole("button", { name: "Actions for team QA" }),
    ];
    for (const control of controls) {
      const size = box(control);
      expect(Math.min(size.width, size.height), control.textContent).toBeGreaterThanOrEqual(TAP);
    }

    // The header spans the column; its height is what counts.
    expect(box(screen.getByRole("button", { name: /^QA/ })).height).toBeGreaterThanOrEqual(TAP);

    await user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));
    for (const control of [
      // Tester leads the team, so its call is the team's (B70).
      await screen.findByRole("button", { name: "Open team QA" }),
      screen.getByRole("button", { name: /working/ }),
    ]) {
      expect(box(control).height).toBeGreaterThanOrEqual(TAP);
    }
  });

  it("are at least 44 points in a chat's tree (B46)", async () => {
    const api = fakeApi();
    api.pixies.mockResolvedValue([pixie()]);
    api.pixieGroups.mockResolvedValue({ s1: [groupEntry()] });
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [session()]));
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));

    const tree = await screen.findByRole("list", { name: "Working in Validate contact form" });
    for (const control of within(tree).getAllByRole("button")) {
      const size = box(control);
      expect(
        Math.min(size.height, size.width || TAP),
        control.getAttribute("aria-label") ?? "",
      ).toBeGreaterThanOrEqual(TAP);
    }
    expect(box(within(tree).getByRole("button", { name: /^Actions for/ }))).toEqual({
      width: TAP,
      height: TAP,
    });
  });

  it("are at least 44 points on a pixie's details", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("web")]);
    await openPixie(api, pixie({ skills: ["review"] }), "Details");

    const controls = [
      screen.getByRole("button", { name: "brook" }),
      screen.getByRole("button", { name: "Colour #E5484D" }),
      screen.getByRole("button", { name: "Custom colour" }),
      screen.getByRole("button", { name: "Remove review" }),
    ];
    for (const control of controls) {
      const { width, height } = box(control);
      expect(
        Math.min(width, height),
        control.getAttribute("aria-label") ?? "",
      ).toBeGreaterThanOrEqual(TAP);
    }
    for (const name of [/^Edit name/, /^Edit slug/, "Add skill", /^Soul/]) {
      expect(box(screen.getByRole("button", { name })).height).toBeGreaterThanOrEqual(TAP);
    }
  });

  it("are at least 44 points for card buttons, switches and colour swatches", async () => {
    const api = fakeApi();
    api.approvals.mockResolvedValue([review()]);
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [session()]));
    const { user } = await renderApp({ api });

    // Text buttons are as wide as their words; their height is what falls short.
    const reach = (control: HTMLElement, sides: "height" | "both" = "both") => {
      const hit = hitBox(control);
      const name = control.textContent || (control.getAttribute("aria-label") ?? "");
      expect(hit.height, name).toBeGreaterThanOrEqual(TAP);
      if (sides === "both") expect(hit.width, name).toBeGreaterThanOrEqual(TAP);
    };
    // A plain card button.
    reach(await screen.findByRole("button", { name: "Feedback" }), "height");
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    reach(screen.getByRole("switch", { name: "Show automated chats" }));
    await user.click(screen.getByRole("tab", { name: "Settings" }));
    // The Settings list's rows.
    reach(await screen.findByRole("button", { name: "Appearance" }), "height");
    await user.click(screen.getByRole("button", { name: "Appearance" }));
    reach(screen.getByRole("button", { name: "Back to Settings" }), "height");
    for (const swatch of within(
      await screen.findByRole("group", { name: "Accent colour" }),
    ).getAllByRole("button")) {
      reach(swatch);
    }
    await user.click(screen.getByRole("button", { name: "Back to Settings" }));
    await user.click(screen.getByRole("button", { name: "Accounts" }));
    reach(await screen.findByRole("button", { name: "Show email" }), "height");
    await user.click(screen.getByRole("button", { name: "Back to Settings" }));
    await user.click(screen.getByRole("button", { name: "Storage" }));
    // The Storage page's buttons (B86).
    reach(await screen.findByRole("button", { name: "Review large attachments" }), "height");
    reach(screen.getByRole("button", { name: "Rebuild" }), "height");
    await user.click(screen.getByRole("button", { name: "Back to Settings" }));
    await user.click(screen.getByRole("button", { name: "Agents" }));
    // A segmented control's segments.
    reach(await screen.findByRole("button", { name: "Current branch" }), "height");
    await user.click(screen.getByRole("button", { name: "Back to Settings" }));
    await user.click(screen.getByRole("button", { name: "Usage" }));
    // The usage page's controls (B84, B86).
    reach(await screen.findByRole("button", { name: "Refresh usage" }), "height");
    reach(screen.getByRole("button", { name: "Week" }), "height");
    reach(screen.getByRole("button", { name: "Previous period" }));
    reach(screen.getByRole("button", { name: "Next period" }));
    reach(screen.getByRole("button", { name: "Details" }), "height");
    await user.click(screen.getByRole("button", { name: "Details" }));
    reach(screen.getByRole("button", { name: "Back to Usage" }), "height");
  });

  it("are at least 44 points for a new chat's place selector", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("cv-page")]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));

    const place = screen.getByRole("button", { name: /^Where the chat works: / });
    expect(hitBox(place).height).toBeGreaterThanOrEqual(TAP);
  });

  it("are at least 44 points for pixie limits, activity links and cards", async () => {
    const chat = session({ id: "s1", title: "Check the form" });
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("cv-page")]);
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
    api.session.mockResolvedValue(detail({ ...chat, id: "pc", pixie_id: "p1" }));
    api.sessionEvents.mockResolvedValue([
      {
        id: 1,
        session_id: "pc",
        type: "pixie.card",
        ts: "x",
        payload: { kind: "session", session_id: "s1" },
      },
    ]);
    api.pixieActivity.mockResolvedValue([
      { id: 1, ts: "2026-10-14T10:00:00Z", tool: "nudge", session_id: "s1", summary: "Nudged" },
    ]);
    const { user } = await openPixie(api, pixie({ chat_session_id: "pc" }));

    const open = within(await screen.findByRole("group", { name: /^Chat:/ })).getByRole("button", {
      name: "Open",
    });
    expect(hitBox(open).height).toBeGreaterThanOrEqual(TAP);
    expect(hitBox(open).width).toBeGreaterThanOrEqual(TAP);

    await user.click(screen.getByRole("tab", { name: "Details" }));
    for (const name of ["Running chats at once", "New chats per day"]) {
      for (const step of within(screen.getByRole("group", { name })).getAllByRole("button")) {
        expect(box(step)).toEqual({ width: TAP, height: TAP });
      }
    }
    await user.click(screen.getByRole("button", { name: /^Activity/ }));
    const link = await screen.findByRole("button", { name: "Check the form" });
    expect(box(link).height).toBeGreaterThanOrEqual(TAP);
  });
});
