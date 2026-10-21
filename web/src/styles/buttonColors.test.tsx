/// <reference types="node" />
import { readFileSync } from "node:fs";
import { fireEvent, screen, within } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { fakeApi } from "../test/fakeApi.ts";
import { detail, event, pixie, report, session } from "../test/fixtures.ts";
import { openPixie } from "../test/pixies.ts";
import { renderApp } from "../test/render.tsx";

// The app's own stylesheets: jsdom resolves which rule wins, though not the variables.
const styles = ["base.css", "screens.css", "chat.css"].map((name) => {
  const style = document.createElement("style");
  style.textContent = readFileSync(`src/styles/${name}`, "utf8");
  return style;
});

beforeAll(() => {
  document.head.append(...styles);
});

afterAll(() => {
  for (const style of styles) style.remove();
});

/**
 * Every primary button on screen keeps `.b-pri`'s label colour, which pairs with its
 * accent fill in light and dark; another rule's colour can leave it blank (B42).
 */
function expectReadablePrimaries() {
  const buttons = [...document.querySelectorAll<HTMLElement>(".b.b-pri")];
  expect(buttons.length).toBeGreaterThan(0);
  for (const button of buttons) {
    const css = getComputedStyle(button);
    expect(css.color, button.textContent).toBe("var(--on-accent)");
  }
}

describe("primary buttons of pixie habits and reports (B42)", () => {
  // New habit sits in the Habits heading row as a plain button since B85; the new fact's
  // Save is the pixie pages' primary button.
  it("keep the accent pair on the Memory page", async () => {
    const { user } = await openPixie(fakeApi(), pixie(), "Details");
    await user.click(screen.getByRole("button", { name: /^Memory/ }));
    const page = screen.getByRole("dialog", { name: "Memory" });
    await user.click(await within(page).findByRole("button", { name: "Add fact" }));
    expect(within(page).getByRole("button", { name: "Save" })).toHaveClass("b-pri");
    expectReadablePrimaries();
  });

  it("keep the accent pair on a suggested habit card", async () => {
    const api = fakeApi();
    const shown = pixie({ chat_session_id: "pc" });
    api.session.mockResolvedValue(detail(session({ id: "pc", repo: "pixie:p1", pixie_id: "p1" })));
    api.sessionEvents.mockResolvedValue([
      event({
        id: 1,
        session_id: "pc",
        type: "pixie.card",
        payload: { kind: "habit_suggestion", habit: { name: "Watch CI", prompt: "Look" } },
      }),
    ]);
    await openPixie(api, shown);
    await screen.findByRole("button", { name: "Start" });
    expectReadablePrimaries();
  });

  it("keep the accent pair on an inbox report", async () => {
    const api = fakeApi();
    api.pixieReports.mockResolvedValue([report()]);
    await renderApp({ api });
    const row = await screen.findByRole("article", { name: /^Report/ });
    fireEvent.click(within(row).getByRole("button", { name: "Show details" }));
    expectReadablePrimaries();
  });
});
