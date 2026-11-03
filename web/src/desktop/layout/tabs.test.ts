// Project tabs, as the Mac's AppStore keeps them: General first, the repos' order, the
// last tab never closes, Ctrl 9 is the last tab, and a dragged tab lands by whole steps.
import { describe, expect, it } from "vitest";
import {
  closeProject,
  moveProject,
  NO_TABS,
  openProject,
  orderAfterAdding,
  reorderOffset,
  reorderTarget,
  repoOrderAfterMove,
  selectPixies,
  selectProjectAt,
  selectProjectOffset,
  shownTab,
  withRepos,
  type Tabs,
} from "./tabs.ts";

const repos = ["todo-ui", "weather-forecast", "map-viewer"];

function threeOpen(): Tabs {
  let tabs = withRepos(NO_TABS, repos);
  tabs = openProject(tabs, "map-viewer", repos);
  tabs = openProject(tabs, "weather-forecast", repos);
  return tabs;
}

describe("project tabs", () => {
  it("open the first project at first, then follow the repos' order", () => {
    expect(withRepos(NO_TABS, repos)).toEqual({
      open: ["todo-ui"],
      current: "todo-ui",
      last: "todo-ui",
    });
    expect(withRepos(NO_TABS, [])).toMatchObject({ open: ["general"], current: "general" });
    expect(threeOpen().open).toEqual(repos);
    expect(openProject(threeOpen(), "general", repos).open[0]).toBe("general");
  });

  it("close tabs of removed projects and keep the Pixies tab chosen", () => {
    const tabs = selectPixies(threeOpen());
    expect(shownTab(tabs)).toBe("pixies");
    const after = withRepos(tabs, ["todo-ui", "map-viewer"]);
    expect(after.open).toEqual(["todo-ui", "map-viewer"]);
    expect(shownTab(after)).toBe("pixies");
    expect(after.last).toBe("todo-ui");
  });

  it("never close the last tab, and move to the neighbour of a closed one", () => {
    let tabs = threeOpen();
    tabs = closeProject(tabs, "weather-forecast");
    expect(tabs).toMatchObject({ open: ["todo-ui", "map-viewer"], current: "todo-ui" });
    tabs = closeProject(tabs, "todo-ui");
    expect(tabs.current).toBe("map-viewer");
    expect(closeProject(tabs, "map-viewer")).toBe(tabs);
  });

  it("select by position, the ninth being the last, and wrap around", () => {
    const tabs = threeOpen();
    expect(selectProjectAt(tabs, 0).current).toBe("todo-ui");
    expect(selectProjectAt(tabs, 8).current).toBe("map-viewer");
    expect(selectProjectAt(tabs, 5)).toBe(tabs);
    const first = selectProjectAt(tabs, 0);
    expect(selectProjectOffset(first, -1).current).toBe("map-viewer");
    expect(selectProjectOffset(first, 1).current).toBe("weather-forecast");
    // From the Pixies tab, the step counts from the project shown before it.
    expect(selectProjectOffset(selectPixies(first), 1).current).toBe("weather-forecast");
  });

  it("move a dragged tab but keep General first", () => {
    const tabs = openProject(threeOpen(), "general", repos);
    expect(moveProject(tabs, "map-viewer", 0).open).toEqual([
      "general",
      "map-viewer",
      "todo-ui",
      "weather-forecast",
    ]);
    expect(moveProject(tabs, "general", 2)).toBe(tabs);
  });
});

describe("the project order saved for every device", () => {
  const all = ["todo-ui", "recipes", "weather-forecast", "map-viewer"];
  const tabs: Tabs = {
    open: ["todo-ui", "weather-forecast", "map-viewer"],
    current: null,
    last: null,
  };

  it("puts a moved project before the open tab that now follows it", () => {
    const after = moveProject(tabs, "map-viewer", 0);
    expect(repoOrderAfterMove(all, tabs, after, "map-viewer")).toEqual([
      "map-viewer",
      "todo-ui",
      "recipes",
      "weather-forecast",
    ]);
  });

  it("puts a project moved to the end after the open tab before it", () => {
    const after = moveProject(tabs, "todo-ui", 2);
    expect(repoOrderAfterMove(all, tabs, after, "todo-ui")).toEqual([
      "recipes",
      "weather-forecast",
      "map-viewer",
      "todo-ui",
    ]);
  });

  it("saves nothing when the tab stayed where it was", () => {
    expect(repoOrderAfterMove(all, tabs, tabs, "todo-ui")).toBeNull();
  });
});

describe("dragging a tab", () => {
  it("lands at the nearest whole step within the strip", () => {
    expect(reorderTarget(1, 170, 182, 4)).toBe(2);
    expect(reorderTarget(1, 80, 182, 4)).toBe(1);
    expect(reorderTarget(1, -91, 182, 4)).toBe(0);
    expect(reorderTarget(1, 2000, 182, 4)).toBe(3);
    expect(reorderTarget(1, 50, 0, 4)).toBe(1);
  });

  it("slides the tabs in between one step toward the start", () => {
    expect([0, 1, 2, 3].map((i) => reorderOffset(i, 0, 2, 10))).toEqual([0, -10, -10, 0]);
    expect([0, 1, 2, 3].map((i) => reorderOffset(i, 3, 1, 10))).toEqual([0, 10, 10, 0]);
  });
});

// Regression (production check, 2026-11-03): after a restart the tabs of projects added
// after the last drag came back in another order, as the saved order named only the
// first two projects and the daemon lists the rest by file name.
describe("the project order after adding a project", () => {
  it("is saved whole, so the new project stays where it shows", () => {
    const before = ["recipes-site", "notes-app"];
    expect(orderAfterAdding(before, [...before, "zeta"])).toEqual([
      "recipes-site",
      "notes-app",
      "zeta",
    ]);
    expect(orderAfterAdding(before, ["notes-app", "recipes-site"])).toBeNull();
    expect(orderAfterAdding(before, ["recipes-site"])).toBeNull();
    // The first load sets nothing.
    expect(orderAfterAdding([], before)).toBeNull();
  });
});
