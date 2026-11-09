import { describe, expect, it } from "vitest";
import {
  FIXED_PAGES,
  listed,
  matches,
  placeLabels,
  placeTitle,
  projectTabs,
  type SettingsPlace,
} from "./catalog.ts";

// Ported from NestKitTests' SettingsCatalogTests.
const page = (id: (typeof FIXED_PAGES)[number] | "addProject"): SettingsPlace => ({ page: id });

describe("the settings catalog", () => {
  it("titles the pages in the Mac's order and finds pages by their rows", () => {
    expect(FIXED_PAGES.map((id) => placeTitle(page(id)))).toEqual([
      "General",
      "Appearance",
      "Notifications",
      "Agents",
      "Computer use",
      "Usage",
      "Performance",
      "Storage",
      "Pixies",
      "Accounts",
      "Devices",
      "Keyboard shortcuts",
      "Configuration",
      "Features",
    ]);
    for (const word of [
      "plugins",
      "marketplaces",
      "skills",
      "mcp servers",
      "connectors",
      "hooks",
    ]) {
      expect(matches(page("configuration"), word)).toBe(true);
    }
    expect(matches(page("accounts"), "plugins")).toBe(false);
    expect(matches(page("storage"), "archive")).toBe(true);
    expect(matches(page("storage"), "search index")).toBe(true);
    expect(matches(page("storage"), "used by nest")).toBe(true);
    expect(matches(page("general"), "archive")).toBe(false);
    expect(matches(page("general"), "storage")).toBe(false);
    expect(matches(page("general"), "show automated chats")).toBe(true);
    expect(matches(page("usage"), "warn me at")).toBe(true);
    expect(matches(page("usage"), "weekly")).toBe(true);
    expect(matches(page("agents"), "warn me at")).toBe(false);
    expect(matches(page("agents"), "stuck chats")).toBe(true);
    expect(placeTitle({ project: "nest" })).toBe("nest");
    expect(placeTitle(page("addProject"))).toBe("Add project");
    expect(matches(page("general"), "  ")).toBe(true);
    expect(matches(page("notifications"), "pixie reports")).toBe(true);
    expect(matches(page("shortcuts"), "new terminal")).toBe(true);
    expect(matches(page("devices"), "grain")).toBe(false);
    for (const place of [...FIXED_PAGES.map(page), { project: "x" }, page("addProject")]) {
      expect(placeLabels(place).length).toBeGreaterThan(0);
    }
  });

  it("lists the pages and projects the query leaves", () => {
    const all = listed(["nest", "cv"], "");
    expect(all.pages).toEqual(FIXED_PAGES.map(page));
    expect(all.projects).toEqual([{ project: "nest" }, { project: "cv" }, page("addProject")]);
    const grain = listed(["nest"], "grain");
    expect(grain.pages).toEqual([page("appearance")]);
    expect(grain.projects).toEqual([]);
    expect(listed(["nest", "cv"], "cv").projects).toEqual([{ project: "cv" }]);
    expect(listed(["nest"], "default branch").projects).toEqual([{ project: "nest" }]);
    // The Features page is found by the daemon's group and feature names.
    expect(listed([], "branch map", ["Branch map"]).pages).toEqual([page("features")]);
  });

  it("gives a plain folder no Worktrees or Triggers tab", () => {
    expect(projectTabs(true)).toEqual([
      "General",
      "Configuration",
      "Chats",
      "Worktrees",
      "Triggers",
      "Look",
      "Artifacts",
    ]);
    expect(matches({ project: "x" }, ".mcp.json")).toBe(true);
    expect(projectTabs(false)).not.toContain("Worktrees");
    expect(projectTabs(false)).not.toContain("Triggers");
  });
});
