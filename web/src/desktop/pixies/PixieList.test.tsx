// The Pixies list's destructive and ordering actions, through the whole desktop app.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { pixie, team } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { browserBridge } from "../bridge.ts";
import { DesktopApp } from "../DesktopApp.tsx";

beforeAll(() => {
  // jsdom has none; the workspace measures itself with one.
  globalThis.ResizeObserver = class {
    observe() {
      return undefined;
    }
    unobserve() {
      return undefined;
    }
    disconnect() {
      return undefined;
    }
  };
  Element.prototype.scrollIntoView = () => undefined;
});

async function renderPixies() {
  const api = fakeApi();
  const pixies = [
    pixie({ id: "a", name: "Ann", slug: "ann", position: 0, team_id: "t1" }),
    pixie({ id: "b", name: "Bea", slug: "bea", position: 1 }),
    pixie({ id: "c", name: "Cal", slug: "cal", position: 2, team_id: "t1" }),
  ];
  api.pixies.mockResolvedValue(pixies);
  api.reorderPixies.mockImplementation((ids) =>
    Promise.resolve(
      ids.flatMap((id, position) => {
        const found = pixies.find((p) => p.id === id);
        return found === undefined ? [] : [{ ...found, position }];
      }),
    ),
  );
  api.teams.mockResolvedValue([team({ id: "t1", name: "QA", handle: "qa", leader_id: "a" })]);
  const storage = memoryStorage();
  render(
    <DesktopApp
      bridge={browserBridge({ search: "" }, null)}
      api={api}
      connect={socketFactory().connect}
      location={{ protocol: "http:", host: "127.0.0.1:8765" }}
      storage={() => storage}
    />,
  );
  fireEvent.click(await screen.findByRole("tab", { name: /^Pixies/ }));
  await screen.findByRole("button", { name: /^Ann, @ann/ });
  return api;
}

const menuOf = (name: RegExp) => {
  fireEvent.contextMenu(screen.getByRole("button", { name }));
  return screen.getByRole("menu");
};

describe("the Pixies list", () => {
  it("deletes a pixie only after its confirmation", async () => {
    const api = await renderPixies();
    fireEvent.click(within(menuOf(/^Bea,/)).getByRole("menuitem", { name: "Delete…" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete Bea?" });
    expect(api.deletePixie).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(api.deletePixie).not.toHaveBeenCalled();

    fireEvent.click(within(menuOf(/^Bea,/)).getByRole("menuitem", { name: "Delete…" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(api.deletePixie).toHaveBeenCalledWith("b");
    });
  });

  it("moves a pixie down within its team, naming every pixie in the new order", async () => {
    const api = await renderPixies();
    const menu = menuOf(/^Ann,/);
    // Bea has no team: Move Down passes over her to Cal, the next in QA.
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Move Down" }));
    await waitFor(() => {
      expect(api.reorderPixies).toHaveBeenCalledWith(["b", "c", "a"]);
    });
    // Ann is last in QA now.
    await waitFor(() => {
      expect(within(menuOf(/^Ann,/)).getByRole("menuitem", { name: "Move Down" })).toHaveAttribute(
        "aria-disabled",
        "true",
      );
    });
  });
});
