/// <reference types="node" />
import { readFileSync } from "node:fs";
import { screen, within } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { pixie, team } from "../../test/fixtures.ts";
import { showPixies } from "../../test/pixies.ts";
import { renderApp } from "../../test/render.tsx";

// The app's own stylesheets, in the order main.tsx loads them: jsdom resolves which rule
// wins, though it lays nothing out.
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

async function openList() {
  const api = fakeApi();
  api.pixies.mockResolvedValue([
    pixie({ id: "a", name: "Ada", slug: "ada", team_id: "qa" }),
    pixie({ id: "b", name: "Bo", slug: "bo", position: 1 }),
  ]);
  api.teams.mockResolvedValue([team({ id: "qa", name: "QA", handle: "qa", leader_id: "a" })]);
  const { user } = await renderApp({ api });
  await showPixies(user);
}

describe("the pixies view's look (B102, as the Mac's B89 list)", () => {
  it("lays a team out as a plain section, its header and members in full width", async () => {
    await openList();

    // No other rule (such as a team call's sprite grid) squeezes the team's section.
    const section = screen.getByRole("region", { name: "QA" });
    expect(getComputedStyle(section).display).toBe("block");
    const member = within(section).getByRole("button", { name: "Ada, @ada, leader" });
    expect(getComputedStyle(member).display).toBe("flex");
  });

  it("writes a pixie's @handle in the body font right after its name, not pushed right", async () => {
    await openList();

    const row = screen.getByRole("button", { name: "Bo, @bo" });
    const handle = row.querySelector<HTMLElement>(".rt + .pxh");
    expect(handle).toHaveTextContent("@bo");
    const css = getComputedStyle(defined(handle));
    expect(css.fontFamily).not.toBe("var(--mono)");
    expect(css.textAlign).not.toBe("right");
  });
});
