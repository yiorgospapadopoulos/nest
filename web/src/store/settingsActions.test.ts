import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client.ts";
import { fakeApi } from "../test/fakeApi.ts";
import {
  codexAccount,
  codexPlugins,
  configurationPage,
  copyPreview,
  projectConfiguration,
} from "../test/fixtures.ts";
import { createActions } from "./actions.ts";
import type { Action } from "./state.ts";

function setup() {
  const api = fakeApi();
  const dispatched: Action[] = [];
  const actions = createActions(
    api,
    (a) => dispatched.push(a),
    () => localStorage,
  );
  return { api, dispatched, actions };
}

const page = configurationPage();
const changes = (dispatched: Action[]) =>
  dispatched.filter((a) => a.type === "settings").map((a) => a.change);

describe("Codex's account (B102 item 26)", () => {
  it("loads with the other settings", async () => {
    const { dispatched, actions } = setup();
    await actions.loadSettings();
    expect(changes(dispatched)[0]).toMatchObject({ codex: codexAccount() });
  });

  it("signs out, keeping the account as it was when the Mac refuses", async () => {
    const { api, dispatched, actions } = setup();
    await actions.codexLogout();
    expect(api.codexLogout).toHaveBeenCalled();
    expect(changes(dispatched)).toEqual([
      { codex: codexAccount({ signed_in: false, email: null, plan: null }) },
    ]);
    api.codexLogout.mockRejectedValueOnce(new ApiError(502, "Codex could not sign out"));
    await actions.codexLogout();
    expect(changes(dispatched)).toHaveLength(1);
    expect(dispatched.at(-1)).toMatchObject({
      type: "toast",
      toast: { text: "Codex could not sign out", tone: "error" },
    });
  });
});

describe("Settings > Configuration (B102 item 31)", () => {
  it("loads the page", async () => {
    const { api, dispatched, actions } = setup();
    expect(await actions.loadConfiguration()).toBe(true);
    expect(changes(dispatched)).toEqual([{ configuration: page }]);
    api.configuration.mockRejectedValueOnce(new Error("down"));
    expect(await actions.loadConfiguration()).toBe(false);
  });

  it("shows the page each write answers with", async () => {
    const { api, dispatched, actions } = setup();
    const server = { transport: "stdio" as const, command: "db", args: [] };
    expect(await actions.setUsesShared("codex", "skills", false)).toBe(true);
    expect(await actions.createSkill("lint", "Lints")).toBe(true);
    expect(await actions.deleteSkill("lint")).toBe(true);
    expect(await actions.makeSkillShared("lint")).toBe(true);
    expect(await actions.setCodexSkill("lint", false)).toBe(true);
    expect(await actions.putMcpServer("db", server)).toBe(true);
    expect(await actions.deleteMcpServer("db")).toBe(true);
    expect(await actions.undoCopy("u1")).toBe(true);
    expect(api.setUsesShared).toHaveBeenCalledWith("codex", "skills", false);
    expect(api.createSkill).toHaveBeenCalledWith("lint", "Lints");
    expect(api.setCodexSkill).toHaveBeenCalledWith("lint", false);
    expect(api.putMcpServer).toHaveBeenCalledWith("db", server);
    expect(api.undoCopy).toHaveBeenCalledWith("u1");
    expect(changes(dispatched)).toHaveLength(8);

    api.deleteSkill.mockRejectedValueOnce(new ApiError(404, "No such skill"));
    expect(await actions.deleteSkill("gone")).toBe(false);
    expect(changes(dispatched)).toHaveLength(8);
    expect(dispatched.at(-1)).toMatchObject({ type: "toast", toast: { text: "No such skill" } });
  });

  it("reads a server for its form, and what a copy would do", async () => {
    const { api, actions } = setup();
    expect(await actions.mcpServer("docs")).toEqual({
      transport: "http",
      url: "https://docs.example.com/mcp",
      headers: {},
    });
    expect(await actions.copyPreview("claude")).toEqual(copyPreview());
    api.copyPreview.mockRejectedValueOnce(new Error("down"));
    expect(await actions.copyPreview("claude")).toBeNull();
  });

  it("copies an engine's setup to Shared, giving the done line and its undo", async () => {
    const { api, dispatched, actions } = setup();
    expect(await actions.copyToShared("claude", false)).toEqual({
      summary: "Copied 1 skill to Shared",
      undo_id: "u1",
    });
    expect(api.copyToShared).toHaveBeenCalledWith("claude", false);
    expect(changes(dispatched)).toEqual([{ configuration: page }]);
    api.copyToShared.mockRejectedValueOnce(new Error("down"));
    expect(await actions.copyToShared("claude", true)).toBeNull();
  });

  it("reads and saves a setup file, telling a change on disk apart", async () => {
    const { api, dispatched, actions } = setup();
    expect(await actions.readConfigFile("/a/AGENTS.md")).toEqual({
      path: "/a/AGENTS.md",
      text: "# Instructions",
      version: "v1",
    });
    expect(await actions.writeConfigFile("/a/AGENTS.md", "# New", "v1")).toEqual({
      version: "v2",
    });
    expect(api.writeConfigurationFile).toHaveBeenCalledWith("/a/AGENTS.md", "# New", "v1");

    api.writeConfigurationFile.mockRejectedValueOnce(
      new ApiError(409, "changed on disk", null, { current_version: "v3" }),
    );
    expect(await actions.writeConfigFile("/a/AGENTS.md", "# New", "v1")).toEqual({
      conflict: "v3",
    });
    api.writeConfigurationFile.mockRejectedValueOnce(new ApiError(409, "deleted", null, {}));
    expect(await actions.writeConfigFile("/a/AGENTS.md", "# New", "v1")).toEqual({
      conflict: null,
    });
    expect(dispatched).toEqual([]);

    api.writeConfigurationFile.mockRejectedValueOnce(new ApiError(403, "Not allowed"));
    expect(await actions.writeConfigFile("/etc/hosts", "x", null)).toBeNull();
    expect(dispatched.at(-1)).toMatchObject({ type: "toast", toast: { text: "Not allowed" } });
  });

  it("lists, installs and removes Codex's plugins and marketplaces", async () => {
    const { api, actions } = setup();
    expect(await actions.codexPlugins("git")).toEqual(codexPlugins());
    expect(api.codexPlugins).toHaveBeenCalledWith("git");
    expect(await actions.installCodexPlugin("github@openai")).toEqual(codexPlugins());
    expect(await actions.uninstallCodexPlugin("github@openai")).toEqual(codexPlugins());
    expect(await actions.codexMarketplaces()).toEqual([{ name: "openai", path: null }]);
    expect(await actions.addCodexMarketplace("me/plugins")).toEqual([
      { name: "openai", path: null },
    ]);
    expect(await actions.removeCodexMarketplace("openai")).toEqual([]);
    expect(api.addCodexMarketplace).toHaveBeenCalledWith("me/plugins");
    expect(api.removeCodexMarketplace).toHaveBeenCalledWith("openai");
  });

  it("loads and changes a project's own setup", async () => {
    const { api, dispatched, actions } = setup();
    const server = { transport: "stdio" as const, command: "db", args: [] };
    expect(await actions.loadProjectConfiguration("cv-page")).toBe(true);
    expect(await actions.putProjectMcpServer("cv-page", "db", server)).toBe(true);
    expect(await actions.deleteProjectMcpServer("cv-page", "db")).toBe(true);
    expect(await actions.createProjectSkill("cv-page", "deploy", "")).toBe(true);
    expect(api.putProjectMcpServer).toHaveBeenCalledWith("cv-page", "db", server);
    expect(api.createProjectSkill).toHaveBeenCalledWith("cv-page", "deploy", "");
    expect(dispatched.filter((a) => a.type === "projectConfiguration")).toHaveLength(4);
    expect(dispatched[0]).toEqual({
      type: "projectConfiguration",
      repo: "cv-page",
      configuration: projectConfiguration(),
    });
    api.projectConfiguration.mockRejectedValueOnce(new Error("down"));
    expect(await actions.loadProjectConfiguration("cv-page")).toBe(false);
  });

  it("loads again what is shown when the engines' files change on disk", async () => {
    const { api, actions } = setup();
    await actions.configurationChanged({ scope: "user", repo: null });
    expect(api.configuration).not.toHaveBeenCalled();

    await actions.loadConfiguration();
    await actions.loadProjectConfiguration("cv-page");
    await actions.configurationChanged({ scope: "user", repo: null });
    expect(api.configuration).toHaveBeenCalledTimes(2);
    await actions.configurationChanged({ scope: "repo", repo: "cv-page" });
    expect(api.projectConfiguration).toHaveBeenCalledTimes(2);
    await actions.configurationChanged({ scope: "repo", repo: "notes" });
    expect(api.projectConfiguration).toHaveBeenCalledTimes(2);
    expect(api.configuration).toHaveBeenCalledTimes(2);
  });

  it("follows a configuration.changed event", async () => {
    const { api, actions } = setup();
    await actions.loadConfiguration();
    actions.receive({
      id: null,
      type: "configuration.changed",
      ts: "2026-10-06T10:00:00Z",
      session_id: null,
      payload: { scope: "user", repo: null },
    });
    await expect.poll(() => api.configuration.mock.calls.length).toBe(2);
  });
});
