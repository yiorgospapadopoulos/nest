import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { pixie, team } from "../../test/fixtures.ts";
import { memoryStorage, renderApp } from "../../test/render.tsx";
import { LONG_PRESS_MS } from "../projects/rowGestures.ts";

const PIXIES = [
  pixie({ id: "a", name: "Ada", slug: "ada", position: 0, team_id: "qa" }),
  pixie({ id: "b", name: "Bo", slug: "bo", position: 1 }),
  pixie({ id: "c", name: "Cy", slug: "cy", position: 2, team_id: "qa" }),
  pixie({ id: "d", name: "Di", slug: "di", position: 3, team_id: "docs" }),
  pixie({ id: "e", name: "Eve", slug: "eve", position: 4, team_id: "lost" }),
];
const TEAMS = [
  team({ id: "docs", name: "Docs", handle: "docs", position: 1, leader_id: "d" }),
  team({ id: "qa", name: "QA", handle: "qa", position: 0, leader_id: "c" }),
  team({ id: "empty", name: "Empty", handle: "empty", position: 2 }),
];

async function openList(api: FakeApi = fakeApi(), storage = memoryStorage()) {
  api.pixies.mockResolvedValue(PIXIES);
  api.teams.mockResolvedValue(TEAMS);
  api.updatePixie.mockImplementation((id, body) =>
    Promise.resolve({ ...defined(PIXIES.find((p) => p.id === id)), ...body }),
  );
  api.updateTeam.mockImplementation((id, body) =>
    Promise.resolve({ ...(TEAMS.find((t) => t.id === id) ?? team({ id })), ...body }),
  );
  api.reorderPixies.mockImplementation((ids) =>
    Promise.resolve(
      ids.map((id, position) => ({ ...defined(PIXIES.find((p) => p.id === id)), position })),
    ),
  );
  const rendered = await renderApp({ api, storage });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  return rendered;
}

const names = (region: HTMLElement) =>
  within(region)
    .queryAllByRole("button", { name: /, @/ })
    .map((b) => b.getAttribute("aria-label"));
const section = (name: string) => screen.getByRole("region", { name });

async function rowMenu(user: Awaited<ReturnType<typeof openList>>["user"], name: string) {
  await user.click(screen.getByRole("button", { name: `Actions for ${name}` }));
  return screen.getByRole("dialog", { name: `Actions for ${name}` });
}

describe("pixie teams in the list", () => {
  it("shows teams as sections with their members, the leader marked, then the rest", async () => {
    await openList();

    expect(names(section("QA"))).toEqual(["Ada, @ada", "Cy, @cy, leader"]);
    expect(names(section("Docs"))).toEqual(["Di, @di, leader"]);
    expect(within(section("Empty")).getByText("No pixies yet")).toBeInTheDocument();
    // A pixie whose team is unknown shows with those in no team.
    expect(names(section("No team"))).toEqual(["Bo, @bo", "Eve, @eve"]);
    expect(within(section("QA")).getByText("Leader")).toBeInTheDocument();
    const order = ["QA", "Docs", "Empty", "No team"].map((n) => section(n));
    for (let i = 1; i < order.length; i += 1) {
      expect(
        defined(order[i - 1]).compareDocumentPosition(defined(order[i])) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  });

  it("keeps the handle apart from the name and the Leader tag, so it gives way first", async () => {
    await openList();
    for (const name of ["Cy, @cy, leader", "Ada, @ada", "Bo, @bo"]) {
      const row = screen.getByRole("button", { name });
      const handle = row.querySelector(".pxslug");
      expect(handle?.textContent).toBe(`@${name.split("@")[1]?.split(",")[0] ?? ""}`);
      // The handle comes after the name and any tag, on its own.
      expect(row.querySelector(".rt + .rm + .pxslug, .rt + .pxslug")).toBe(handle);
    }
    const tag = within(section("QA")).getByText("Leader");
    expect(tag.closest(".rm")?.textContent).toBe("Leader");
  });

  it("folds a team and remembers it on this device", async () => {
    const storage = memoryStorage();
    const { user, unmount } = await openList(fakeApi(), storage);

    const header = screen.getByRole("button", { name: /^QA/ });
    expect(header).toHaveAttribute("aria-expanded", "true");
    await user.click(header);
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(names(section("QA"))).toEqual([]);
    unmount();

    const again = await openList(fakeApi(), storage);
    expect(screen.getByRole("button", { name: /^QA/ })).toHaveAttribute("aria-expanded", "false");
    await again.user.click(screen.getByRole("button", { name: /^QA/ }));
    expect(names(section("QA"))).toHaveLength(2);
  });

  it("creates a team after asking for its name", async () => {
    const api = fakeApi();
    api.createTeam.mockResolvedValue(team({ id: "new", name: "Ops", handle: "ops", position: 3 }));
    const { user } = await openList(api);

    await user.click(screen.getByRole("button", { name: "New team" }));
    const sheet = screen.getByRole("dialog", { name: "New team" });
    await user.click(within(sheet).getByRole("button", { name: "Create" }));
    expect(await screen.findByText("Type a name")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog", { name: "New team" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New team" }));
    await user.type(screen.getByLabelText("Team name"), "  Ops {Enter}");
    expect(api.createTeam).toHaveBeenCalledWith({ name: "Ops" });
    expect(await screen.findByRole("region", { name: "Ops" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "New team" })).not.toBeInTheDocument();
  });

  it("keeps the new team sheet open when creating fails", async () => {
    const api = fakeApi();
    api.createTeam.mockRejectedValue(new ApiError(409, "That handle is taken"));
    const { user } = await openList(api);

    await user.click(screen.getByRole("button", { name: "New team" }));
    await user.type(screen.getByLabelText("Team name"), "QA");
    await user.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByText("That handle is taken")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "New team" })).toBeInTheDocument();
  });
});

describe("pixie row menu", () => {
  it("opens with the dots button and a long press", async () => {
    const { user } = await openList();
    await rowMenu(user, "Ada");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    const row = screen.getByRole("button", { name: "Ada, @ada" });
    vi.useFakeTimers();
    fireEvent.pointerDown(row, { button: 0, clientX: 10, clientY: 10 });
    act(() => {
      vi.advanceTimersByTime(LONG_PRESS_MS);
    });
    fireEvent.pointerUp(row);
    fireEvent.click(row);
    vi.useRealTimers();
    expect(screen.getByRole("dialog", { name: "Actions for Ada" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Chat" })).not.toBeInTheDocument();
  });

  it("opens the pixie on its chat or its details", async () => {
    const { user } = await openList();
    let menu = await rowMenu(user, "Ada");
    await user.click(within(menu).getByRole("menuitem", { name: "Open" }));
    expect(screen.getByRole("tab", { name: "Chat", selected: true })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to Projects" }));

    menu = await rowMenu(user, "Ada");
    await user.click(within(menu).getByRole("menuitem", { name: "Details" }));
    expect(screen.getByRole("tab", { name: "Details", selected: true })).toBeInTheDocument();
  });

  it("duplicates a pixie", async () => {
    const api = fakeApi();
    api.duplicatePixie.mockResolvedValue(
      pixie({ id: "a2", name: "Ada 2", slug: "ada-2", position: 1, team_id: "qa" }),
    );
    const { user } = await openList(api);
    const menu = await rowMenu(user, "Ada");
    await user.click(within(menu).getByRole("menuitem", { name: "Duplicate" }));

    expect(api.duplicatePixie).toHaveBeenCalledWith("a");
    expect(await within(section("QA")).findByRole("button", { name: "Ada 2, @ada-2" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("moves a pixie to a team or out of its team", async () => {
    const api = fakeApi();
    const { user } = await openList(api);

    let menu = await rowMenu(user, "Bo");
    await user.click(within(menu).getByRole("menuitem", { name: "Move to team" }));
    const picker = screen.getByRole("dialog", { name: "Move Bo to" });
    expect(within(picker).getByRole("menuitemradio", { name: "No team" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await user.click(within(picker).getByRole("menuitemradio", { name: "Docs" }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("b", { team_id: "docs" });
    await waitFor(() => {
      expect(names(section("Docs"))).toContain("Bo, @bo");
    });

    menu = await rowMenu(user, "Ada");
    await user.click(within(menu).getByRole("menuitem", { name: "Move to team" }));
    await user.click(screen.getByRole("menuitemradio", { name: "No team" }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("a", { team_id: null });
  });

  it("moves a pixie up and down among its section", async () => {
    const api = fakeApi();
    const { user } = await openList(api);

    let menu = await rowMenu(user, "Ada");
    expect(within(menu).getByRole("menuitem", { name: "Move Up" })).toBeDisabled();
    await user.click(within(menu).getByRole("menuitem", { name: "Move Down" }));
    expect(api.reorderPixies).toHaveBeenLastCalledWith(["b", "c", "a", "d", "e"]);

    await waitFor(() => {
      expect(names(section("QA"))).toEqual(["Cy, @cy, leader", "Ada, @ada"]);
    });
    menu = await rowMenu(user, "Ada");
    expect(within(menu).getByRole("menuitem", { name: "Move Down" })).toBeDisabled();
    await user.click(within(menu).getByRole("menuitem", { name: "Move Up" }));
    expect(api.reorderPixies).toHaveBeenLastCalledWith(["b", "a", "c", "d", "e"]);

    menu = await rowMenu(user, "Eve");
    expect(within(menu).getByRole("menuitem", { name: "Move Down" })).toBeDisabled();
  });

  it("hides and shows a pixie", async () => {
    const api = fakeApi();
    const { user } = await openList(api);
    let menu = await rowMenu(user, "Bo");
    await user.click(within(menu).getByRole("menuitem", { name: "Hide" }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("b", { hidden: true });
    await waitFor(() => {
      expect(names(section("No team"))).toEqual(["Eve, @eve"]);
    });

    await user.click(screen.getByRole("button", { name: "Show hidden (1)" }));
    menu = await rowMenu(user, "Bo");
    await user.click(within(menu).getByRole("menuitem", { name: "Show" }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("b", { hidden: false });
  });

  it("closes the menu when the pixie is deleted elsewhere", async () => {
    const { user, push } = await openList();
    await rowMenu(user, "Bo");
    push({ type: "pixie.deleted", payload: { pixie_id: "b" } });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("deletes a pixie once confirmed", async () => {
    const api = fakeApi();
    const { user } = await openList(api);
    let menu = await rowMenu(user, "Bo");
    await user.click(within(menu).getByRole("menuitem", { name: "Delete…" }));
    const confirm = screen.getByRole("alertdialog", { name: "Delete Bo?" });
    expect(confirm).toHaveTextContent("Its chat, soul and memory go too. This can't be undone.");
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(api.deletePixie).not.toHaveBeenCalled();

    menu = await rowMenu(user, "Bo");
    await user.click(within(menu).getByRole("menuitem", { name: "Delete…" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(api.deletePixie).toHaveBeenCalledWith("b");
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Bo, @bo" })).not.toBeInTheDocument();
    });
  });
});

describe("team header menu", () => {
  async function teamMenu(user: Awaited<ReturnType<typeof openList>>["user"], name: string) {
    await user.click(screen.getByRole("button", { name: `Actions for team ${name}` }));
    return screen.getByRole("dialog", { name: `Actions for team ${name}` });
  }

  it("renames a team", async () => {
    const api = fakeApi();
    const { user } = await openList(api);
    let menu = await teamMenu(user, "QA");
    await user.click(within(menu).getByRole("menuitem", { name: "Rename" }));
    const field = screen.getByLabelText("Team name");
    expect(field).toHaveValue("QA");
    await user.clear(field);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Type a name")).toBeInTheDocument();
    await user.type(field, "Testers{Enter}");
    expect(api.updateTeam).toHaveBeenCalledWith("qa", { name: "Testers" });
    expect(await screen.findByRole("region", { name: "Testers" })).toBeInTheDocument();

    menu = await teamMenu(user, "Testers");
    await user.click(within(menu).getByRole("menuitem", { name: "Rename" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the rename sheet open when the Mac refuses the name", async () => {
    const api = fakeApi();
    const { user } = await openList(api);
    api.updateTeam.mockRejectedValueOnce(new ApiError(422, "Too long"));
    const menu = await teamMenu(user, "QA");
    await user.click(within(menu).getByRole("menuitem", { name: "Rename" }));
    await user.type(screen.getByLabelText("Team name"), "!{Enter}");
    expect(await screen.findByText("Too long")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Rename team" })).toBeInTheDocument();
  });

  it("changes the handle, showing why the Mac refused one", async () => {
    const api = fakeApi();
    const { user } = await openList(api);
    api.updateTeam.mockRejectedValueOnce(new ApiError(409, "That handle is taken"));
    const menu = await teamMenu(user, "QA");
    await user.click(within(menu).getByRole("menuitem", { name: "Change handle" }));
    const field = screen.getByLabelText("Handle");
    expect(field).toHaveValue("qa");
    await user.clear(field);
    await user.type(field, "ada{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("That handle is taken");
    expect(screen.getByRole("dialog", { name: "Change handle" })).toBeInTheDocument();

    await user.clear(field);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(api.updateTeam).toHaveBeenCalledTimes(1);
    await user.type(field, "@testers");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(api.updateTeam).toHaveBeenLastCalledWith("qa", { handle: "testers" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(screen.getByText("@testers")).toBeInTheDocument();
  });

  it("closes the handle sheet when the handle did not change", async () => {
    const api = fakeApi();
    const { user } = await openList(api);
    const menu = await teamMenu(user, "QA");
    await user.click(within(menu).getByRole("menuitem", { name: "Change handle" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(api.updateTeam).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("sets the leader among the members", async () => {
    const api = fakeApi();
    const { user } = await openList(api);
    const menu = await teamMenu(user, "QA");
    await user.click(within(menu).getByRole("menuitem", { name: "Set leader" }));
    const picker = screen.getByRole("dialog", { name: "Leader of QA" });
    expect(within(picker).getByRole("menuitemradio", { name: "Cy" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await user.click(within(picker).getByRole("menuitemradio", { name: "Ada" }));
    expect(api.updateTeam).toHaveBeenCalledWith("qa", { leader_id: "a" });
    await waitFor(() => {
      expect(names(section("QA"))).toEqual(["Ada, @ada, leader", "Cy, @cy"]);
    });
  });

  it("offers no leader to set in an empty team", async () => {
    const { user } = await openList();
    const menu = await teamMenu(user, "Empty");
    expect(within(menu).getByRole("menuitem", { name: "Set leader" })).toBeDisabled();
  });

  it("deletes a team once confirmed, keeping its pixies", async () => {
    const api = fakeApi();
    const { user } = await openList(api);
    let menu = await teamMenu(user, "QA");
    await user.click(within(menu).getByRole("menuitem", { name: "Delete team…" }));
    const confirm = screen.getByRole("alertdialog", { name: "Delete QA?" });
    expect(confirm).toHaveTextContent("Its pixies stay, without a team.");
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(api.deleteTeam).not.toHaveBeenCalled();

    menu = await teamMenu(user, "QA");
    await user.click(within(menu).getByRole("menuitem", { name: "Delete team…" }));
    await user.click(screen.getByRole("button", { name: "Delete team" }));
    expect(api.deleteTeam).toHaveBeenCalledWith("qa");
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "QA" })).not.toBeInTheDocument();
    });
    expect(names(section("No team"))).toEqual(["Ada, @ada", "Bo, @bo", "Cy, @cy", "Eve, @eve"]);
  });

  it("follows team events from other devices", async () => {
    const { push } = await openList();
    push({
      type: "pixie_team.updated",
      payload: { team: { ...team({ id: "qa", name: "Bugs" }) } },
    });
    expect(screen.getByRole("region", { name: "Bugs" })).toBeInTheDocument();
    push({ type: "pixie_team.deleted", payload: { id: "docs" } });
    expect(screen.queryByRole("region", { name: "Docs" })).not.toBeInTheDocument();
  });
});
