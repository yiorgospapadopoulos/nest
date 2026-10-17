import { describe, expect, it } from "vitest";
import { parseRoute, routePath } from "./routes.ts";

describe("routes", () => {
  it.each([
    ["/", { tab: "inbox", chat: null }],
    ["/inbox", { tab: "inbox", chat: null }],
    ["/projects", { tab: "projects", chat: null }],
    ["/account", { tab: "settings", chat: null }],
    ["/settings", { tab: "settings", chat: null }],
    ["/settings/agents", { tab: "settings", chat: null, settings: { page: "agents" } }],
    ["/settings/elsewhere", { tab: "inbox", chat: null }],
    ["/settings/agents/x", { tab: "inbox", chat: null }],
    ["/settings/agents/usage", { tab: "settings", chat: null, settings: { detail: "usage" } }],
    ["/settings/agents/usage/x", { tab: "inbox", chat: null }],
    ["/settings/usage", { tab: "settings", chat: null, settings: { page: "usage" } }],
    ["/settings/storage", { tab: "settings", chat: null, settings: { page: "storage" } }],
    ["/settings/usage/details", { tab: "settings", chat: null, settings: { detail: "usage" } }],
    ["/settings/usage/details/x", { tab: "inbox", chat: null }],
    ["/settings/usage/x", { tab: "inbox", chat: null }],
    ["/settings/devices/usage", { tab: "inbox", chat: null }],
    [
      "/settings/projects/cv%20page",
      { tab: "settings", chat: null, settings: { project: "cv page" } },
    ],
    ["/settings/projects/", { tab: "inbox", chat: null }],
    ["/settings/projects", { tab: "inbox", chat: null }],
    ["/settings/projects/a/b", { tab: "inbox", chat: null }],
    ["/settings/projects/%E0%A4%A", { tab: "inbox", chat: null }],
    ["/chat/s%2F1", { tab: "projects", chat: "s/1" }],
    ["/chat/", { tab: "inbox", chat: null }],
    ["/chat/a/b", { tab: "inbox", chat: null }],
    ["/chat/%E0%A4%A", { tab: "inbox", chat: null }],
    ["/account/x", { tab: "inbox", chat: null }],
    ["/pixie/p%2F1", { tab: "projects", chat: null, pixie: "p/1" }],
    ["/pixie/", { tab: "inbox", chat: null }],
    ["/pixie/a/b", { tab: "inbox", chat: null }],
    ["/pixie/%E0%A4%A", { tab: "inbox", chat: null }],
    ["/elsewhere", { tab: "inbox", chat: null }],
  ])("reads %s", (path, route) => {
    expect(parseRoute(path)).toEqual(route);
  });

  it("writes paths that read back the same", () => {
    for (const route of [
      { tab: "settings", chat: null },
      { tab: "settings", chat: null, settings: { page: "devices" } },
      { tab: "settings", chat: null, settings: { project: "cv page/x" } },
      { tab: "settings", chat: null, settings: { detail: "usage" } },
      { tab: "projects", chat: "s/1 x" },
      { tab: "projects", chat: null, pixie: "p/1 x" },
    ] as const) {
      expect(parseRoute(routePath(route))).toEqual(route);
    }
    expect(routePath({ tab: "inbox", chat: null })).toBe("/inbox");
    expect(routePath({ tab: "settings", chat: null, settings: { detail: "usage" } })).toBe(
      "/settings/usage/details",
    );
  });
});
