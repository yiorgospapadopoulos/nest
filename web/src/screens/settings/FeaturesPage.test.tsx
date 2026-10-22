import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { FeaturesCatalog } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { feature, featureGroup, featuresCatalog } from "../../test/fixtures.ts";
import { memoryStorage, renderApp } from "../../test/render.tsx";
import { openSettings } from "../../test/settings.ts";

// Settings > Features (B103): what makes Nest different, by area, with what is new.

const GROUPS_KEY = "nest.features.groups";

/** Getting around with one new feature, Chats and Worktrees without. */
function withNew(): FeaturesCatalog {
  return featuresCatalog([
    featureGroup({
      features: [
        feature({ new: true }),
        feature({ id: "split-workspace", name: "Split workspace", where: "Workspace" }),
      ],
    }),
    featureGroup({
      id: "chats",
      name: "Chats",
      features: [
        feature({
          id: "composer-shortcuts",
          name: "Composer shortcuts",
          text: "`/` for commands, `@` for files.",
          where: "Composer",
        }),
      ],
    }),
    featureGroup({
      id: "git",
      name: "Worktrees and git",
      features: [
        feature({ id: "branch-map", name: "Branch map", where: "Sidebar", new: true }),
        feature({ id: "issues", name: "Issues become chats", where: "Start screen", new: true }),
      ],
    }),
  ]);
}

function apiWith(catalog: FeaturesCatalog) {
  const api = fakeApi();
  api.features.mockResolvedValue(catalog);
  api.markFeaturesSeen.mockResolvedValue(catalog);
  return api;
}

// A feature's row, from its name.
const row = (name: HTMLElement) => defined(name.closest<HTMLElement>(".feat"));

/** A fake Mac that, like the daemon, stops calling a feature new once it was shown. */
function daemonLike(start: FeaturesCatalog) {
  const api = fakeApi();
  let catalog = start;
  api.features.mockImplementation(() => Promise.resolve(catalog));
  api.markFeaturesSeen.mockImplementation((ids) => {
    const groups = catalog.groups.map((g) => ({
      ...g,
      features: g.features.map((f) => (ids.includes(f.id) ? { ...f, new: false } : f)),
    }));
    catalog = featuresCatalog(groups);
    return Promise.resolve(catalog);
  });
  return api;
}

const group = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}`) });

describe("the Features row in Settings", () => {
  it("sits after Configuration with how many are new and a dot", async () => {
    await openSettings(null, { api: apiWith(withNew()) });

    const row = await screen.findByRole("button", { name: "Features, 3 new" });
    expect(within(row).getByText("3 new")).toBeInTheDocument();
    expect(row.querySelector(".sdot")).not.toBeNull();
    expect(row.querySelector("svg")).not.toBeNull();
  });

  it("shows no count and no dot when nothing is new", async () => {
    await openSettings(null);

    const row = await screen.findByRole("button", { name: "Features" });
    await waitFor(() => {
      expect(row).toHaveTextContent(/^Features$/);
    });
    expect(row.querySelector(".sdot")).toBeNull();
  });

  it("opens the page and goes back to Settings", async () => {
    const { user } = await openSettings("Features");

    expect(window.location.pathname).toBe("/settings/features");
    expect(screen.getByRole("heading", { name: "Features" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to Settings" }));
    expect(window.location.pathname).toBe("/settings");
  });

  it("opens from its address", async () => {
    window.history.replaceState(null, "", "/settings/features");
    const { api } = await renderApp();

    expect(await screen.findByRole("heading", { name: "Features" })).toBeInTheDocument();
    expect(api.features).toHaveBeenCalled();
    window.history.replaceState(null, "", "/");
  });
});

describe("the Features page", () => {
  it("shows the intro with the new count, and the groups with their counts", async () => {
    const { user } = await openSettings(null, { api: apiWith(withNew()) });
    await user.click(await screen.findByRole("button", { name: "Features, 3 new" }));

    expect(
      await screen.findByText(
        "What makes Nest different, by area. The README has every detail. 3 new since your last update.",
      ),
    ).toBeInTheDocument();
    expect(group("Getting around")).toHaveTextContent(/^Getting around2$/);
    expect(group("Chats")).toHaveTextContent(/^Chats1$/);
    expect(group("Worktrees and git")).toHaveTextContent(/^Worktrees and git2$/);
  });

  it("leaves the count out of the intro when nothing is new", async () => {
    await openSettings("Features");

    expect(
      await screen.findByText("What makes Nest different, by area. The README has every detail."),
    ).toBeInTheDocument();
  });

  it("opens the groups with something new, each feature with its badge, text and place", async () => {
    const { user } = await openSettings(null, { api: apiWith(withNew()) });
    await user.click(await screen.findByRole("button", { name: "Features, 3 new" }));

    await screen.findByText("Needs you", { selector: ".fname" });
    expect(group("Getting around")).toHaveAttribute("aria-expanded", "true");
    expect(group("Chats")).toHaveAttribute("aria-expanded", "false");
    expect(group("Worktrees and git")).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByText("Composer shortcuts")).not.toBeInTheDocument();

    const needsYou = row(screen.getByText("Needs you", { selector: ".fname" }));
    expect(within(needsYou).getByText("New")).toBeInTheDocument();
    expect(
      within(needsYou).getByText(
        "Everything waiting on you in one list: approvals, questions, reviews and merges.",
      ),
    ).toBeInTheDocument();
    expect(within(needsYou).getByText("Right panel")).toHaveClass("fwhere");
    const split = row(screen.getByText("Split workspace"));
    expect(within(split).queryByText("New")).not.toBeInTheDocument();
    expect(screen.getAllByText("New")).toHaveLength(3);

    // A small dot just before the count of each group showing something new.
    const dot = (name: string) => group(name).querySelector(".ft-dot");
    expect(dot("Getting around")?.nextElementSibling).toHaveClass("ft-n");
    expect(dot("Getting around")).toHaveAttribute("aria-hidden", "true");
    expect(dot("Worktrees and git")).not.toBeNull();
    expect(dot("Chats")).toBeNull();
  });

  it("shows backtick spans as inline code", async () => {
    const { user } = await openSettings("Features");

    await user.click(group("Chats"));

    const shortcuts = row(screen.getByText("Composer shortcuts"));
    expect([...shortcuts.querySelectorAll("code")].map((code) => code.textContent)).toEqual([
      "/",
      "@",
    ]);
    expect(shortcuts).toHaveTextContent("/ for commands and skills, @ for files and pixies.");
  });

  it("waits for the catalog", async () => {
    const api = fakeApi();
    api.features.mockReturnValue(new Promise<FeaturesCatalog>(() => undefined));
    await openSettings("Features", { api });

    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(api.markFeaturesSeen).not.toHaveBeenCalled();
  });
});

describe("what the page reports as shown", () => {
  it("reports the features of the open groups when it shows", async () => {
    const api = apiWith(withNew());
    const { user } = await openSettings(null, { api });
    await user.click(await screen.findByRole("button", { name: "Features, 3 new" }));

    await waitFor(() => {
      expect(api.markFeaturesSeen).toHaveBeenCalledTimes(1);
    });
    expect(api.markFeaturesSeen).toHaveBeenCalledWith([
      "needs-you",
      "split-workspace",
      "branch-map",
      "issues",
    ]);
  });

  it("reports nothing when every group is closed, then each group opened", async () => {
    const api = fakeApi();
    const { user } = await openSettings("Features", { api });
    await screen.findByText(/^What makes Nest different/);
    expect(api.markFeaturesSeen).not.toHaveBeenCalled();

    await user.click(group("Chats"));
    expect(api.markFeaturesSeen).toHaveBeenLastCalledWith(["composer-shortcuts"]);
    await user.click(group("Getting around"));
    expect(api.markFeaturesSeen).toHaveBeenLastCalledWith([
      "needs-you",
      "split-workspace",
      "composer-shortcuts",
    ]);
    await user.click(group("Chats"));
    expect(api.markFeaturesSeen).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Composer shortcuts")).not.toBeInTheDocument();
  });

  it("keeps the badges and the row's count until Settings is left", async () => {
    const api = daemonLike(withNew());
    const { user } = await openSettings(null, { api });
    await user.click(await screen.findByRole("button", { name: "Features, 3 new" }));
    await waitFor(() => {
      expect(api.markFeaturesSeen).toHaveBeenCalledTimes(1);
    });

    // Still in Settings after the report: the badges, the intro and the open groups stay.
    expect(await screen.findByText(/3 new since your last update\.$/)).toBeInTheDocument();
    expect(screen.getAllByText("New")).toHaveLength(3);
    expect(group("Getting around")).toHaveAttribute("aria-expanded", "true");
    expect(group("Worktrees and git")).toHaveAttribute("aria-expanded", "true");

    // The row counts the same features as the badges, which show again when it is opened.
    await user.click(screen.getByRole("button", { name: "Back to Settings" }));
    const row = await screen.findByRole("button", { name: "Features, 3 new" });
    expect(row.querySelector(".sdot")).not.toBeNull();
    await user.click(row);
    expect(screen.getAllByText("New")).toHaveLength(3);
    expect(screen.getByText(/3 new since your last update\.$/)).toBeInTheDocument();
    expect(group("Worktrees and git")).toHaveAttribute("aria-expanded", "true");

    // Leaving the Settings tab ends the visit: nothing is new when it shows the page again.
    await user.click(screen.getByRole("tab", { name: "Needs you" }));
    expect(screen.queryByRole("heading", { name: "Features" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Settings" }));
    expect(
      await screen.findByText("What makes Nest different, by area. The README has every detail."),
    ).toBeInTheDocument();
    expect(screen.queryByText("New")).not.toBeInTheDocument();
    expect(group("Getting around")).toHaveAttribute("aria-expanded", "false");
    expect(group("Worktrees and git")).toHaveAttribute("aria-expanded", "false");
    expect(document.querySelector(".ft-dot")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Back to Settings" }));
    const plain = await screen.findByRole("button", { name: "Features" });
    expect(plain.querySelector(".sdot")).toBeNull();
  });

  it("keeps the page as it was when the report fails, without a message", async () => {
    const api = apiWith(withNew());
    api.markFeaturesSeen.mockRejectedValue(new ApiError(500, "Server down"));
    const { user } = await openSettings(null, { api });
    await user.click(await screen.findByRole("button", { name: "Features, 3 new" }));

    await waitFor(() => {
      expect(api.markFeaturesSeen).toHaveBeenCalled();
    });
    expect(screen.getByText(/3 new since your last update\.$/)).toBeInTheDocument();
    expect(screen.queryByText("Server down")).not.toBeInTheDocument();
  });
});

describe("the groups remembered on this device", () => {
  it("keeps the user's choice over the default", async () => {
    const storage = memoryStorage();
    const api = apiWith(withNew());
    const first = await openSettings(null, { api, storage });
    await screen.findByRole("button", { name: "Features, 3 new" });
    await first.user.click(screen.getByRole("button", { name: "Features, 3 new" }));
    await first.user.click(group("Getting around"));
    await first.user.click(group("Chats"));

    expect(JSON.parse(storage.getItem(GROUPS_KEY) ?? "")).toEqual({
      around: false,
      chats: true,
    });
    first.unmount();

    window.history.replaceState(null, "", "/settings/features");
    await renderApp({ api, storage });
    await screen.findByText("Composer shortcuts");
    expect(group("Getting around")).toHaveAttribute("aria-expanded", "false");
    expect(group("Chats")).toHaveAttribute("aria-expanded", "true");
    expect(group("Worktrees and git")).toHaveAttribute("aria-expanded", "true");
    window.history.replaceState(null, "", "/");
  });

  it("still opens and closes groups when storage is unavailable", async () => {
    const broken = memoryStorage();
    broken.getItem = (key: string) => {
      if (key === GROUPS_KEY) throw new Error("blocked");
      return null;
    };
    broken.setItem = (key: string) => {
      if (key === GROUPS_KEY) throw new Error("blocked");
    };
    const { user } = await openSettings("Features", { storage: broken });

    await user.click(group("Chats"));
    expect(group("Chats")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Composer shortcuts")).toBeInTheDocument();
  });
});
