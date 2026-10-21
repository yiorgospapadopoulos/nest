import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { ConfigurationPage } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { configurationPage, copyPreview, engineSection, skillItem } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";
import { openSettings } from "../../test/settings.ts";

const openConfiguration = (api = fakeApi()) => openSettings("Configuration", { api });
const region = (name: string | RegExp) => screen.getByRole("region", { name });
const none = { instructions: false, skills: [], mcp_servers: [] };

const codex = engineSection({
  id: "codex",
  name: "Codex",
  account: "me@example.com · ChatGPT Plus",
  bundled_version: "0.40.0",
  config_folder: "/Users/me/.codex",
  uses_shared: {
    instructions: { on: true, fixed: true },
    skills: { on: false, fixed: false },
    mcp_servers: { on: true, fixed: false },
  },
  items: [
    { kind: "plugins", count: 0, detail: null, path: null, folder: false },
    { kind: "rules", count: 3, detail: null, path: "/Users/me/.codex/rules", folder: true },
  ],
});

function withPage(page: ConfigurationPage) {
  const api = fakeApi();
  api.configuration.mockResolvedValue(page);
  return api;
}

describe("configuration page", () => {
  it("opens from Extensions' old address", async () => {
    window.history.replaceState(null, "", "/settings/extensions");
    const { api } = await renderApp();

    expect(await screen.findByRole("heading", { name: "Configuration" })).toBeInTheDocument();
    expect(api.configuration).toHaveBeenCalled();
    window.history.replaceState(null, "", "/");
  });

  it("shows the intro, Shared, the engines and the footer, with no Mac-only buttons", async () => {
    const api = fakeApi();
    const { user } = await openConfiguration(api);

    expect(window.location.pathname).toBe("/settings/configuration");
    expect(screen.getByText(/What your agents read/)).toBeInTheDocument();
    const shared = await screen.findByRole("region", { name: "Shared" });
    expect(within(shared).getByText("AGENTS.md")).toBeInTheDocument();
    expect(within(shared).getByText(/Read by Codex as it is/)).toHaveTextContent(
      "Read by Codex as it is; Claude's CLAUDE.md imports it. ~/.agents/AGENTS.md",
    );
    expect(within(shared).getByRole("button", { name: /^Skills/ })).toHaveTextContent("Skills 1");
    expect(within(shared).getByRole("button", { name: /^MCP servers/ })).toHaveTextContent(
      "MCP servers 1",
    );
    expect(screen.getByText(/Other engines appear here/)).toBeInTheDocument();
    expect(screen.queryByText(/Open in VS Code|Open folder|Reveal in Finder/)).toBeNull();

    // The first engine opens until the user picks one.
    const claude = region("Claude");
    expect(within(claude).getByRole("button", { name: /^Claude/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(within(claude).getByText("me@example.com · Claude Max")).toBeInTheDocument();
    expect(within(claude).getByText("Claude Code 2.1.1, bundled with Nest")).toBeInTheDocument();
    expect(within(claude).getByText("~/.claude")).toBeInTheDocument();
    expect(within(claude).getByText("Hooks")).toBeInTheDocument();
    expect(within(claude).getByText("2")).toBeInTheDocument();
    expect(within(claude).getByText("Edit these as files on the Mac.")).toBeInTheDocument();
    // Nothing missing: no copy offered.
    expect(within(claude).queryByRole("button", { name: /Copy Claude/ })).toBeNull();

    await user.click(within(claude).getByRole("button", { name: /^Claude/ }));
    expect(within(claude).queryByText("Hooks")).toBeNull();
  });

  it("opens one engine at a time, and closes one that is gone", async () => {
    const api = withPage(configurationPage({ engines: [engineSection(), codex] }));
    const { user, push } = await openConfiguration(api);

    const codexBox = await screen.findByRole("region", { name: "Codex" });
    const codexHeader = within(codexBox).getByRole("button", { name: /^Codex/ });
    expect(codexHeader).toHaveAttribute("aria-expanded", "false");
    await user.click(codexHeader);
    expect(codexHeader).toHaveAttribute("aria-expanded", "true");
    expect(within(region("Claude")).getByRole("button", { name: /^Claude/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(within(codexBox).getByText("Codex 0.40.0, bundled with Nest")).toBeInTheDocument();
    expect(within(codexBox).getByText("Rules")).toBeInTheDocument();
    expect(within(codexBox).getByText("Codex's own · none")).toBeInTheDocument();
    expect(
      within(codexBox).getByRole("switch", { name: "Uses shared instructions" }),
    ).toBeDisabled();
    expect(within(codexBox).getByText("Codex's own AGENTS.md is the shared one.")).toBeVisible();
    expect(within(codexBox).getByRole("switch", { name: "Uses shared skills" })).not.toBeChecked();

    api.configuration.mockResolvedValue(configurationPage());
    push({ type: "configuration.changed", payload: { scope: "global" } });
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Codex" })).toBeNull();
    });
    // The open engine went; none is opened for the user.
    expect(within(region("Claude")).getByRole("button", { name: /^Claude/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("switches what an engine uses from Shared", async () => {
    const api = fakeApi();
    api.setUsesShared.mockResolvedValue(
      configurationPage({
        engines: [
          engineSection({
            uses_shared: {
              instructions: { on: false, fixed: false },
              skills: { on: true, fixed: true },
              mcp_servers: { on: true, fixed: false },
            },
          }),
        ],
      }),
    );
    const { user } = await openConfiguration(api);

    await user.click(await screen.findByRole("switch", { name: "Uses shared instructions" }));

    expect(api.setUsesShared).toHaveBeenCalledWith("claude", "instructions", false);
    expect(await screen.findByText("Claude's own folder is the shared one.")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Uses shared instructions" })).not.toBeChecked();
  });

  it("waits for the page, and says when it cannot load", async () => {
    const api = fakeApi();
    api.configuration.mockRejectedValue(new ApiError(502, "cannot read ~/.claude"));
    await openConfiguration(api);

    expect(await screen.findByText("cannot read ~/.claude")).toBeInTheDocument();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows where Claude's rules are while the shared file is empty", async () => {
    const page = configurationPage({
      engines: [engineSection({ missing_from_shared: { ...none, instructions: true } })],
    });
    page.shared.instructions = {
      path: "/Users/me/.agents/AGENTS.md",
      exists: false,
      version: null,
    };
    await openConfiguration(withPage(page));

    expect(await screen.findByText(/Your rules are in Claude's CLAUDE.md/)).toHaveTextContent(
      "Empty. Your rules are in Claude's CLAUDE.md; copy them here to share them with every engine. ~/.agents/AGENTS.md",
    );
  });
});

describe("shared skills", () => {
  const skills = [
    skillItem({ name: "release-notes", description: "Writes release notes" }),
    skillItem({
      name: "chrome",
      source: "synced",
      read_only: true,
      codex_enabled: false,
      path: "/Users/me/.claude/skills/chrome/SKILL.md",
    }),
    skillItem({
      name: "hatch-pet",
      source: "engine_only",
      engine: "codex",
      codex_enabled: null,
      codex_error: null,
    }),
    skillItem({
      name: "broken",
      codex_error: "bad front matter",
      source: "plugin",
      plugin: "sp",
      read_only: true,
    }),
    skillItem({ name: "fifth" }),
  ];
  const page = () => {
    const found = configurationPage({ engines: [engineSection(), codex] });
    found.shared.skills.items = skills;
    return found;
  };

  it("lists the skills with where they come from, four until asked for all", async () => {
    const { user } = await openConfiguration(withPage(page()));

    await user.click(await screen.findByRole("button", { name: /^Skills/ }));
    const list = screen.getByRole("list", { name: "Shared skills" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(4);
    expect(within(list).getByText("Writes release notes")).toBeInTheDocument();
    expect(within(list).getByText("claude.ai account")).toBeInTheDocument();
    expect(within(list).getAllByText("read only")).toHaveLength(2);
    expect(within(list).getByText("Found in Codex's own skills folder")).toBeInTheDocument();
    expect(within(list).getByText("Codex only")).toBeInTheDocument();
    expect(within(list).getByText("not loaded by Codex")).toBeInTheDocument();
    expect(within(list).getByRole("switch", { name: "Load chrome in Codex" })).not.toBeChecked();
    expect(within(list).queryByRole("switch", { name: "Load release-notes in Codex" })).toBeNull();
    expect(within(list).queryByRole("button", { name: "Edit chrome" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Show all 5" }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(5);
    await user.click(screen.getByRole("button", { name: "Show fewer" }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(4);

    await user.click(screen.getByRole("button", { name: /^Skills/ }));
    expect(screen.queryByRole("list", { name: "Shared skills" })).toBeNull();
  });

  it("loads a skill in Codex, makes one shared, and removes one after a question", async () => {
    const api = withPage(page());
    api.setCodexSkill.mockResolvedValue(page());
    api.makeSkillShared.mockResolvedValue(page());
    api.deleteSkill.mockResolvedValue(page());
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: /^Skills/ }));

    await user.click(screen.getByRole("switch", { name: "Load chrome in Codex" }));
    expect(api.setCodexSkill).toHaveBeenCalledWith("chrome", true);
    await user.click(screen.getByRole("button", { name: "Make hatch-pet shared" }));
    expect(api.makeSkillShared).toHaveBeenCalledWith("hatch-pet");

    await user.click(screen.getByRole("button", { name: "Remove release-notes" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(api.deleteSkill).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Remove release-notes" }));
    const ask = screen.getByRole("alertdialog", { name: "Remove release-notes?" });
    await user.click(within(ask).getByRole("button", { name: "Remove" }));
    expect(api.deleteSkill).toHaveBeenCalledWith("release-notes");
    expect(screen.queryByRole("button", { name: "Remove chrome" })).toBeNull();
  });

  it("makes a new skill, then opens it in the editor", async () => {
    const api = fakeApi();
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: /^Skills/ }));

    await user.click(screen.getByRole("button", { name: "New skill" }));
    const form = screen.getByRole("dialog", { name: "New skill" });
    expect(form).toHaveTextContent("Made in the shared skills folder, so every engine can use it.");
    const create = within(form).getByRole("button", { name: "Create" });
    expect(create).toBeDisabled();
    await user.type(within(form).getByLabelText("Name"), "Bad Name");
    expect(within(form).getByText("Lower case letters, digits and dashes only.")).toBeVisible();
    await user.clear(within(form).getByLabelText("Name"));
    await user.type(within(form).getByLabelText("Name"), "release-notes");
    await user.type(within(form).getByLabelText("Description"), "When releasing");
    await user.click(create);

    expect(api.createSkill).toHaveBeenCalledWith("release-notes", "When releasing");
    const editor = await screen.findByRole("dialog", { name: "release-notes" });
    expect(api.configurationFile).toHaveBeenCalledWith(
      "/Users/me/.agents/skills/release-notes/SKILL.md",
    );
    expect(editor).toHaveTextContent("shared skill");
  });

  it("keeps the form when the skill cannot be made, and closes it on Cancel", async () => {
    const api = fakeApi();
    api.createSkill.mockRejectedValue(new ApiError(409, "a skill with this name exists"));
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: /^Skills/ }));
    await user.click(screen.getByRole("button", { name: "New skill" }));
    await user.type(screen.getByLabelText("Name"), "review");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("a skill with this name exists")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog", { name: "New skill" })).toBeNull();
  });
});

describe("configuration editor", () => {
  it("edits the shared instructions and saves them", async () => {
    const api = fakeApi();
    const { user } = await openConfiguration(api);

    await user.click(await screen.findByRole("button", { name: "Edit instructions" }));
    const sheet = screen.getByRole("dialog", { name: "Instructions" });
    expect(sheet).toHaveTextContent("~/.agents/AGENTS.md · used by Claude and Codex");
    expect(sheet).toHaveTextContent("Saved files apply from each chat's next message.");
    const text = await within(sheet).findByDisplayValue("# Instructions");
    await user.type(text, "\nBe brief.");
    await user.click(within(sheet).getByRole("button", { name: "Save" }));

    expect(api.writeConfigurationFile).toHaveBeenCalledWith(
      "/Users/me/.agents/AGENTS.md",
      "# Instructions\nBe brief.",
      "v1",
    );
    expect(await screen.findByText("Saved Instructions")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Instructions" })).toBeNull();
  });

  it("offers Reload or Keep mine when the file changed on disk before saving", async () => {
    const api = fakeApi();
    api.writeConfigurationFile
      .mockRejectedValueOnce(new ApiError(409, "changed", null, { current_version: "v9" }))
      .mockResolvedValue({ version: "v10" });
    api.configurationFile
      .mockResolvedValueOnce({ path: "/p", text: "old", version: "v1" })
      .mockResolvedValue({ path: "/p", text: "theirs", version: "v9" });
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: "Edit instructions" }));
    const sheet = screen.getByRole("dialog", { name: "Instructions" });
    const text = await within(sheet).findByDisplayValue("old");
    await user.type(text, " mine");
    await user.click(within(sheet).getByRole("button", { name: "Save" }));

    expect(
      await within(sheet).findByText("This file changed on disk since you opened it."),
    ).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Keep mine" }));
    expect(within(sheet).queryByText(/changed on disk/)).toBeNull();
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    expect(api.writeConfigurationFile).toHaveBeenLastCalledWith(
      "/Users/me/.agents/AGENTS.md",
      "old mine",
      "v9",
    );
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Instructions" })).toBeNull();
    });
  });

  it("reloads the file on disk, dropping the draft", async () => {
    const api = fakeApi();
    api.writeConfigurationFile.mockRejectedValue(new ApiError(409, "changed"));
    api.configurationFile
      .mockResolvedValueOnce({ path: "/p", text: "old", version: "v1" })
      .mockResolvedValue({ path: "/p", text: "theirs", version: "v9" });
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: "Edit instructions" }));
    const sheet = screen.getByRole("dialog", { name: "Instructions" });
    await user.type(await within(sheet).findByDisplayValue("old"), "!");
    await user.click(within(sheet).getByRole("button", { name: "Save" }));

    await user.click(await within(sheet).findByRole("button", { name: "Reload" }));

    expect(await within(sheet).findByDisplayValue("theirs")).toBeInTheDocument();
    expect(within(sheet).queryByText(/changed on disk/)).toBeNull();
  });

  it("follows a change on disk: an untouched draft takes it, an edited one asks", async () => {
    const api = fakeApi();
    api.configurationFile
      .mockResolvedValueOnce({ path: "/p", text: "one", version: "v1" })
      .mockResolvedValueOnce({ path: "/p", text: "two", version: "v2" })
      .mockResolvedValueOnce({ path: "/p", text: "two", version: "v2" })
      .mockResolvedValue({ path: "/p", text: "three", version: "v3" });
    const { user, push } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: "Edit instructions" }));
    const sheet = screen.getByRole("dialog", { name: "Instructions" });
    await within(sheet).findByDisplayValue("one");

    // Each load answers with a new page, as the Mac does.
    api.configuration.mockImplementation(() => Promise.resolve(configurationPage()));
    push({ type: "configuration.changed", payload: { scope: "global" } });
    expect(await within(sheet).findByDisplayValue("two")).toBeInTheDocument();

    // The same version again changes nothing.
    push({ type: "configuration.changed", payload: { scope: "global" } });
    await waitFor(() => {
      expect(api.configurationFile).toHaveBeenCalledTimes(3);
    });
    await user.type(within(sheet).getByDisplayValue("two"), " edited");
    push({ type: "configuration.changed", payload: { scope: "global" } });
    expect(
      await within(sheet).findByText("This file changed on disk since you opened it."),
    ).toBeInTheDocument();
    expect(within(sheet).getByDisplayValue("two edited")).toBeInTheDocument();
  });

  it("stays open when the Mac refuses the text, and Cancel closes it", async () => {
    const api = fakeApi();
    api.writeConfigurationFile.mockRejectedValue(new ApiError(422, "invalid TOML"));
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: "Edit instructions" }));
    const sheet = screen.getByRole("dialog", { name: "Instructions" });
    await within(sheet).findByDisplayValue("# Instructions");
    await user.click(within(sheet).getByRole("button", { name: "Save" }));

    expect(await screen.findByText("invalid TOML")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Instructions" })).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog", { name: "Instructions" })).toBeNull();
  });

  it("ignores a file read after the sheet closed, and keeps the draft when Reload fails", async () => {
    const api = fakeApi();
    let late: (value: { path: string; text: string; version: string }) => void = () => undefined;
    api.configurationFile.mockReturnValueOnce(
      new Promise((resolve) => {
        late = resolve;
      }),
    );
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: "Edit instructions" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    late({ path: "/p", text: "late", version: "v1" });
    expect(screen.queryByRole("dialog", { name: "Instructions" })).toBeNull();

    api.writeConfigurationFile.mockRejectedValue(new ApiError(409, "changed"));
    await user.click(screen.getByRole("button", { name: "Edit instructions" }));
    const sheet = screen.getByRole("dialog", { name: "Instructions" });
    await user.type(await within(sheet).findByDisplayValue("# Instructions"), "!");
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    api.configurationFile.mockRejectedValue(new ApiError(502, "disk gone"));
    await user.click(await within(sheet).findByRole("button", { name: "Reload" }));

    expect(await screen.findByText("disk gone")).toBeInTheDocument();
    expect(within(sheet).getByDisplayValue("# Instructions!")).toBeInTheDocument();
  });

  it("closes when the file cannot be read", async () => {
    const api = fakeApi();
    api.configurationFile.mockRejectedValue(new ApiError(404, "not allowed"));
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: "Edit instructions" }));

    expect(await screen.findByText("not allowed")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Instructions" })).toBeNull();
    });
  });

  it("edits a skill", async () => {
    const api = fakeApi();
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: /^Skills/ }));
    await user.click(screen.getByRole("button", { name: "Edit review" }));

    expect(await screen.findByRole("dialog", { name: "review" })).toHaveTextContent(
      "~/.agents/skills/review/SKILL.md · skill",
    );
    expect(api.configurationFile).toHaveBeenCalledWith("/Users/me/.agents/skills/review/SKILL.md");
  });
});

describe("shared mcp servers", () => {
  const page = () => {
    const found = configurationPage();
    found.shared.mcp_servers.push({
      name: "linear",
      summary: "https://mcp.linear.app/sse",
      transport: "sse",
      engines: ["claude"],
      convertible: false,
      reason: "Codex cannot connect to SSE servers",
    });
    found.shared.mcp_servers.push({
      name: "odd",
      summary: "odd-server",
      transport: "stdio",
      engines: ["claude"],
      convertible: false,
      reason: null,
    });
    return found;
  };

  it("lists the servers with the engines that use them", async () => {
    const { user } = await openConfiguration(withPage(page()));
    await user.click(await screen.findByRole("button", { name: /^MCP servers/ }));

    const list = screen.getByRole("list", { name: "Shared MCP servers" });
    const [docs, linear, odd] = within(list).getAllByRole("listitem");
    expect(docs).toHaveTextContent("docshttps://docs.example.com/mcpClaude · CodexEdit");
    expect(linear).toHaveTextContent("Claude only: Codex cannot connect to SSE servers");
    expect(odd).toHaveTextContent("odd-serverClaude onlyEdit");
    expect(screen.getByText(/Set up once; Nest writes each/)).toBeInTheDocument();
  });

  it("adds a command server", async () => {
    const api = fakeApi();
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: /^MCP servers/ }));
    await user.click(screen.getByRole("button", { name: "Add server" }));

    const form = screen.getByRole("dialog", { name: "Add server" });
    expect(form).toHaveTextContent(
      "Nest writes it into every engine that uses shared MCP servers.",
    );
    const add = within(form).getByRole("button", { name: "Add" });
    expect(add).toBeDisabled();
    await user.type(within(form).getByLabelText("Name"), "playwright");
    await user.type(within(form).getByLabelText("Command"), "npx");
    await user.type(within(form).getByLabelText("Arguments"), "@playwright/mcp");
    await user.type(within(form).getByLabelText("Environment"), "DEBUG=1");
    expect(within(form).queryByRole("button", { name: "Remove" })).toBeNull();
    await user.click(add);

    expect(api.putMcpServer).toHaveBeenCalledWith("playwright", {
      transport: "stdio",
      command: "npx",
      args: ["@playwright/mcp"],
      env: { DEBUG: "1" },
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Add server" })).toBeNull();
    });
  });

  it("edits a URL server, keeping the form when refused, and removes one", async () => {
    const api = fakeApi();
    api.putMcpServer.mockRejectedValueOnce(new ApiError(422, "bad URL"));
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: /^MCP servers/ }));
    await user.click(screen.getByRole("button", { name: "Edit docs" }));

    const form = await screen.findByRole("dialog", { name: "Edit docs" });
    expect(api.mcpServer).toHaveBeenCalledWith("docs");
    expect(within(form).queryByLabelText("Name")).toBeNull();
    expect(within(form).getByRole("button", { name: "HTTP" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(within(form).getByRole("button", { name: "SSE" }));
    await user.type(within(form).getByLabelText("Headers"), "X: 1");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("bad URL")).toBeInTheDocument();
    expect(api.putMcpServer).toHaveBeenCalledWith("docs", {
      transport: "sse",
      url: "https://docs.example.com/mcp",
      headers: { X: "1" },
    });

    await user.click(within(form).getByRole("button", { name: "Command" }));
    expect(within(form).getByLabelText("Command")).toBeInTheDocument();
    await user.click(within(form).getByRole("button", { name: "Remove" }));
    const ask = screen.getByRole("alertdialog", { name: "Remove docs?" });
    expect(ask).toHaveTextContent("It is removed from every engine that uses shared MCP servers.");
    await user.click(within(ask).getByRole("button", { name: "Remove" }));
    expect(api.deleteMcpServer).toHaveBeenCalledWith("docs");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Edit docs" })).toBeNull();
    });
  });

  it("does not open the form when the server cannot be read", async () => {
    const api = fakeApi();
    api.mcpServer.mockRejectedValue(new ApiError(404, "no such server"));
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: /^MCP servers/ }));
    await user.click(screen.getByRole("button", { name: "Edit docs" }));

    expect(await screen.findByText("no such server")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Edit docs" })).toBeNull();
  });

  it("keeps the form when the server cannot be removed, and Cancel closes it", async () => {
    const api = fakeApi();
    api.deleteMcpServer.mockRejectedValue(new ApiError(502, "cannot write"));
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: /^MCP servers/ }));
    await user.click(screen.getByRole("button", { name: "Edit docs" }));
    const form = await screen.findByRole("dialog", { name: "Edit docs" });
    await user.click(within(form).getByRole("button", { name: "Remove" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Remove" }),
    );

    expect(await screen.findByText("cannot write")).toBeInTheDocument();
    await user.click(within(form).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog", { name: "Edit docs" })).toBeNull();
  });
});

describe("copy to shared", () => {
  const missing = () =>
    configurationPage({
      engines: [
        engineSection({
          missing_from_shared: { instructions: true, skills: ["lint"], mcp_servers: [] },
        }),
      ],
    });

  it("shows what the copy does, compares the files, and copies with Undo", async () => {
    const api = withPage(missing());
    api.configurationFile.mockImplementation((path) =>
      Promise.resolve({
        path,
        text: path.endsWith("CLAUDE.md") ? "claude rules" : "",
        version: null,
      }),
    );
    const { user } = await openConfiguration(api);

    const claude = await screen.findByRole("region", { name: "Claude" });
    expect(within(claude).getByText("Not in Shared yet: instructions, 1 skill")).toBeVisible();
    await user.click(within(claude).getByRole("button", { name: "Copy Claude's setup to Shared" }));

    const popup = await screen.findByRole("dialog", { name: "Copy Claude's setup to Shared" });
    expect(api.copyPreview).toHaveBeenCalledWith("claude");
    expect(popup).toHaveTextContent("Only the instructions file is replaced.");
    const warning = within(popup).getByText(/Your shared instructions will be replaced/);
    expect(warning).toHaveClass("cfg-warn");
    expect(within(popup).getByText("Add 1")).toBeInTheDocument();
    expect(within(popup).getByText("lint")).toBeInTheDocument();
    expect(within(popup).getByText("1 already in Shared, left as they are")).toBeInTheDocument();
    expect(within(popup).getByText("Stays Claude only")).toBeInTheDocument();

    await user.click(within(popup).getByRole("button", { name: "Compare the two files" }));
    expect(await within(popup).findByText("claude rules")).toBeInTheDocument();
    expect(within(popup).getByText("Empty")).toBeInTheDocument();
    await user.click(within(popup).getByRole("button", { name: "Hide the files" }));
    expect(within(popup).queryByText("claude rules")).toBeNull();

    const keep = within(popup).getByRole("checkbox", { name: "Keep instructions as they are" });
    await user.click(keep);
    expect(warning).not.toHaveClass("cfg-warn");
    await user.click(keep);
    await user.click(within(popup).getByRole("button", { name: "Copy to Shared" }));

    expect(api.copyToShared).toHaveBeenCalledWith("claude", true);
    expect(await within(claude).findByText("Copied 1 skill to Shared")).toBeInTheDocument();
    expect(within(claude).getByText("Shared matches Claude")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(within(claude).getByRole("button", { name: "Undo" }));
    expect(api.undoCopy).toHaveBeenCalledWith("u1");
    await waitFor(() => {
      expect(within(claude).queryByText("Copied 1 skill to Shared")).toBeNull();
    });
  });

  it("keeps the instructions when asked, and leaves them out when nothing replaces them", async () => {
    const api = withPage(missing());
    api.copyPreview
      .mockResolvedValueOnce(copyPreview())
      .mockResolvedValueOnce(copyPreview({ instructions: null }));
    api.copyToShared.mockRejectedValueOnce(new ApiError(502, "cannot copy"));
    const { user } = await openConfiguration(api);
    const claude = await screen.findByRole("region", { name: "Claude" });

    await user.click(within(claude).getByRole("button", { name: /^Copy Claude/ }));
    const popup = await screen.findByRole("dialog", { name: /^Copy Claude/ });
    await user.click(
      within(popup).getByRole("checkbox", { name: "Keep instructions as they are" }),
    );
    await user.click(within(popup).getByRole("button", { name: "Copy to Shared" }));
    expect(api.copyToShared).toHaveBeenCalledWith("claude", false);
    expect(await screen.findByText("cannot copy")).toBeInTheDocument();
    await user.click(within(popup).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(within(claude).getByRole("button", { name: /^Copy Claude/ }));
    const again = await screen.findByRole("dialog", { name: /^Copy Claude/ });
    expect(within(again).queryByText("Instructions")).toBeNull();
    expect(again).not.toHaveTextContent("Only the instructions file is replaced.");
  });

  it("opens no popup when the preview cannot load, and keeps the done line on a failed Undo", async () => {
    const api = withPage(missing());
    api.copyPreview.mockRejectedValueOnce(new ApiError(502, "no preview"));
    api.undoCopy.mockRejectedValue(new ApiError(410, "too late to undo"));
    const { user } = await openConfiguration(api);
    const claude = await screen.findByRole("region", { name: "Claude" });

    await user.click(within(claude).getByRole("button", { name: /^Copy Claude/ }));
    expect(await screen.findByText("no preview")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(within(claude).getByRole("button", { name: /^Copy Claude/ }));
    await user.click(await screen.findByRole("button", { name: "Copy to Shared" }));
    await user.click(await within(claude).findByRole("button", { name: "Undo" }));
    expect(await screen.findByText("too late to undo")).toBeInTheDocument();
    expect(within(claude).getByText("Copied 1 skill to Shared")).toBeInTheDocument();
  });

  it("keeps the compare closed when a file cannot be read", async () => {
    const api = withPage(missing());
    api.configurationFile.mockImplementation((path) =>
      path.endsWith("CLAUDE.md")
        ? Promise.resolve({ path, text: "claude rules", version: "v1" })
        : Promise.reject(new ApiError(404, "gone")),
    );
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: /^Copy Claude/ }));
    const popup = await screen.findByRole("dialog", { name: /^Copy Claude/ });

    await user.click(within(popup).getByRole("button", { name: "Compare the two files" }));

    expect(await screen.findByText("gone")).toBeInTheDocument();
    expect(within(popup).getByRole("button", { name: "Compare the two files" })).toBeVisible();

    // Claude's own file cannot be read either: the shared one is not asked for.
    api.configurationFile.mockClear();
    api.configurationFile.mockRejectedValue(new ApiError(404, "no CLAUDE.md"));
    await user.click(within(popup).getByRole("button", { name: "Compare the two files" }));
    expect(await screen.findByText("no CLAUDE.md")).toBeInTheDocument();
    expect(api.configurationFile).toHaveBeenCalledTimes(1);
    expect(within(popup).queryByText("Shared now")).toBeNull();
  });
});

describe("claude code engine line", () => {
  it("shows a copy found on the Mac", async () => {
    const page = configurationPage({
      engines: [
        engineSection({ standalone: { path: "/opt/homebrew/bin/claude", version: "2.1.0" } }),
      ],
    });
    await openConfiguration(withPage(page));

    expect(
      await screen.findByText("Also on this Mac: /opt/homebrew/bin/claude 2.1.0"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Install Claude Code" })).toBeNull();
  });

  it("says why the install could not start, and offers it again", async () => {
    const api = fakeApi();
    api.installClaudeCode.mockRejectedValue(new ApiError(409, "already installing"));
    const { user } = await openConfiguration(api);
    const claude = await screen.findByRole("region", { name: "Claude" });

    await user.click(within(claude).getByRole("button", { name: "Install Claude Code" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Install" }),
    );

    expect(await screen.findByText("already installing")).toBeInTheDocument();
    expect(within(claude).queryByText("Installing")).toBeNull();
    expect(within(claude).getByRole("button", { name: "Install Claude Code" })).toBeEnabled();
  });

  it("installs Claude Code after a confirmation and follows the progress", async () => {
    const api = fakeApi();
    const { user, push } = await openConfiguration(api);
    const claude = await screen.findByRole("region", { name: "Claude" });

    await user.click(within(claude).getByRole("button", { name: "Install Claude Code" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(api.installClaudeCode).not.toHaveBeenCalled();
    await user.click(within(claude).getByRole("button", { name: "Install Claude Code" }));
    const confirm = screen.getByRole("alertdialog", { name: "Install Claude Code?" });
    expect(confirm).toHaveTextContent("Nest runs Anthropic's installer");
    await user.click(within(confirm).getByRole("button", { name: "Install" }));

    expect(api.installClaudeCode).toHaveBeenCalled();
    expect(await within(claude).findByText("Installing")).toBeInTheDocument();
    push({ type: "claude_code.install", payload: { state: "running", message: "Downloading" } });
    expect(within(claude).getByText("Downloading")).toBeInTheDocument();
    push({ type: "claude_code.install", payload: { state: "failed", message: "No network" } });
    expect(within(claude).getByRole("alert")).toHaveTextContent("Installing failed: No network");
    push({ type: "claude_code.install", payload: { state: "failed", message: null } });
    expect(within(claude).getByRole("alert")).toHaveTextContent(
      "Installing failed: no reason given",
    );
    push({ type: "claude_code.install", payload: { state: "done", message: null } });
    expect(within(claude).queryByRole("alert")).toBeNull();
  });
});
