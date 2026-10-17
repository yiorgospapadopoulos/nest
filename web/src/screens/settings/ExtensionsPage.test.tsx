import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { AvailablePlugin, PluginDetails } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { claudeCode, installedPlugin, marketplace, pluginDetails } from "../../test/fixtures.ts";
import { openSettings } from "../../test/settings.ts";

const openExtensions = (api = fakeApi()) => openSettings("Extensions", { api });
const section = (name: string) => screen.getByRole("region", { name });

function available(overrides: Partial<AvailablePlugin> = {}): AvailablePlugin {
  return {
    id: "pdf-viewer@official",
    name: "pdf-viewer",
    marketplace: "official",
    description: "View and annotate PDFs",
    version: "1.2.0",
    source: "./plugins/pdf-viewer",
    install_count: 120,
    installed: false,
    ...overrides,
  };
}

describe("claude code", () => {
  it("shows the installed version and path, and the agents' version", async () => {
    await openExtensions();

    const box = await screen.findByRole("region", { name: "Claude Code" });
    expect(within(box).getByText("2.1.3")).toBeInTheDocument();
    expect(within(box).getByText("/Users/me/.local/bin/claude")).toBeInTheDocument();
    expect(within(box).getByText("2.1.1")).toBeInTheDocument();
  });

  it("shows an unknown version and no path", async () => {
    const api = fakeApi();
    api.claudeCode.mockResolvedValue(claudeCode({ version: null, path: null }));
    await openExtensions(api);

    expect(await screen.findByText("Unknown version")).toBeInTheDocument();
    expect(screen.queryByText("Path")).not.toBeInTheDocument();
  });

  it("installs Claude Code after a confirmation and follows the progress", async () => {
    const api = fakeApi();
    api.claudeCode.mockResolvedValue(claudeCode({ installed: false, path: null, version: null }));
    const { user, push } = await openExtensions(api);

    await user.click(await screen.findByRole("button", { name: "Install Claude Code" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(api.installClaudeCode).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Install Claude Code" }));
    const confirm = screen.getByRole("alertdialog", { name: "Install Claude Code?" });
    expect(confirm).toHaveTextContent("official installer");
    await user.click(within(confirm).getByRole("button", { name: "Install" }));

    expect(api.installClaudeCode).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: "Installing..." })).toBeDisabled();
    push({ type: "claude_code.install", payload: { state: "running", message: "Downloading" } });
    expect(within(section("Claude Code")).getByText("Downloading")).toBeInTheDocument();
    push({ type: "claude_code.install", payload: { state: "failed", message: "No network" } });
    expect(within(section("Claude Code")).getByRole("alert")).toHaveTextContent("No network");
    push({ type: "claude_code.install", payload: { state: "done", message: null } });
    push({ type: "claude_code.updated", payload: { ...claudeCode() } });
    expect(within(section("Claude Code")).getByText("2.1.3")).toBeInTheDocument();
  });

  it("says why the install could not start", async () => {
    const api = fakeApi();
    api.claudeCode.mockResolvedValue(claudeCode({ installed: false }));
    api.installClaudeCode.mockRejectedValue(new ApiError(409, "already installing"));
    const { user } = await openExtensions(api);

    await user.click(await screen.findByRole("button", { name: "Install Claude Code" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Install" }),
    );

    expect(await screen.findByText("already installing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install Claude Code" })).toBeEnabled();
  });

  it("waits for the Mac", async () => {
    const api = fakeApi();
    api.claudeCode.mockReturnValue(new Promise(() => undefined));
    await openExtensions(api);

    expect(section("Claude Code")).toHaveTextContent("Loading...");
  });
});

describe("skills and plugins", () => {
  it("lists the plugins, the standalone skills and the marketplaces", async () => {
    const api = fakeApi();
    api.plugins.mockResolvedValue([
      installedPlugin(),
      installedPlugin({ id: "x@local", name: "x", marketplace: "local", version: null }),
    ]);
    api.skills.mockResolvedValue([
      { name: "deploy", description: "Ship it", path: "/Users/me/.claude/skills/deploy" },
      { name: "plain", description: null, path: "/Users/me/.claude/skills/plain" },
    ]);
    api.marketplaces.mockResolvedValue([
      marketplace(),
      marketplace({ name: "mine", kind: "directory", source: null }),
    ]);
    await openExtensions(api);

    const plugins = await screen.findByRole("region", { name: /^Plugins/ });
    expect(within(plugins).getByText("official, 4.1.0")).toBeInTheDocument();
    expect(within(plugins).getByText("local")).toBeInTheDocument();
    expect(within(plugins).getByRole("switch", { name: /superpowers/ })).toBeChecked();
    const skills = section("Skills");
    expect(within(skills).getByText("Ship it")).toBeInTheDocument();
    expect(within(skills).getByText("plain")).toBeInTheDocument();
    const markets = section("Marketplaces");
    expect(within(markets).getByText("anthropics/claude-plugins")).toBeInTheDocument();
    expect(within(markets).getByText("mine")).toBeInTheDocument();
  });

  it("says when no plugin is installed, and leaves Skills out without any", async () => {
    const api = fakeApi();
    api.plugins.mockResolvedValue([]);
    await openExtensions(api);

    expect(await screen.findByText("None installed")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Skills" })).not.toBeInTheDocument();
  });

  it("waits for the lists, and toasts when they cannot load", async () => {
    const api = fakeApi();
    api.skills.mockRejectedValue(new ApiError(502, "claude plugin failed"));
    await openExtensions(api);

    expect(await screen.findByText("claude plugin failed")).toBeInTheDocument();
    expect(section("Plugins")).toHaveTextContent("Loading...");
  });

  it("switches a plugin off, and back on when the Mac refuses", async () => {
    const api = fakeApi();
    api.plugins.mockResolvedValue([
      installedPlugin(),
      installedPlugin({ id: "x@official", name: "x", enabled: false }),
    ]);
    api.setPluginEnabled
      .mockResolvedValueOnce(null)
      .mockRejectedValueOnce(new ApiError(502, "cannot enable"));
    const { user } = await openExtensions(api);
    const toggle = await screen.findByRole("switch", { name: /superpowers/ });

    await user.click(toggle);
    expect(api.setPluginEnabled).toHaveBeenCalledWith("superpowers@official", false);
    expect(screen.getByRole("switch", { name: /superpowers/ })).not.toBeChecked();
    expect(screen.getByRole("switch", { name: /^x/ })).not.toBeChecked();

    await user.click(screen.getByRole("switch", { name: /superpowers/ }));
    expect(await screen.findByText("cannot enable")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /superpowers/ })).not.toBeChecked();
  });

  it("removes a plugin after a confirmation, then loads the list again", async () => {
    const api = fakeApi();
    const { user } = await openExtensions(api);

    await user.click(await screen.findByRole("button", { name: "Remove superpowers" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(api.uninstallPlugin).not.toHaveBeenCalled();
    api.plugins.mockResolvedValue([]);
    await user.click(screen.getByRole("button", { name: "Remove superpowers" }));
    await user.click(
      within(screen.getByRole("alertdialog", { name: "Remove superpowers?" })).getByRole("button", {
        name: "Remove",
      }),
    );

    expect(api.uninstallPlugin).toHaveBeenCalledWith("superpowers@official");
    expect(await screen.findByText("Removed superpowers")).toBeInTheDocument();
    expect(await screen.findByText("None installed")).toBeInTheDocument();
  });

  it("says why a plugin could not be removed", async () => {
    const api = fakeApi();
    api.uninstallPlugin.mockRejectedValue(new ApiError(502, "uninstall failed"));
    const { user } = await openExtensions(api);

    await user.click(await screen.findByRole("button", { name: "Remove superpowers" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Remove" }),
    );

    expect(await screen.findByText("uninstall failed")).toBeInTheDocument();
    expect(api.plugins).toHaveBeenCalledTimes(1);
  });

  it("adds and removes a marketplace", async () => {
    const api = fakeApi();
    const { user } = await openExtensions(api);

    await user.click(await screen.findByRole("button", { name: "Add marketplace" }));
    await user.click(screen.getByRole("button", { name: "Close" }));
    await user.click(screen.getByRole("button", { name: "Add marketplace" }));
    await user.type(screen.getByLabelText("Source"), "me/plugins");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(api.addMarketplace).toHaveBeenCalledWith("me/plugins");
    expect(await screen.findByText("Marketplace added")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove official" }));
    await user.click(
      within(screen.getByRole("alertdialog", { name: "Remove official?" })).getByRole("button", {
        name: "Remove",
      }),
    );
    expect(api.removeMarketplace).toHaveBeenCalledWith("official");
    expect(await screen.findByText("Removed official")).toBeInTheDocument();
  });

  it("keeps the source when a marketplace cannot be added", async () => {
    const api = fakeApi();
    api.addMarketplace.mockRejectedValue(new ApiError(502, "not a marketplace"));
    const { user } = await openExtensions(api);

    await user.click(await screen.findByRole("button", { name: "Add marketplace" }));
    await user.type(screen.getByLabelText("Source"), "nope");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(await screen.findByText("not a marketplace")).toBeInTheDocument();
    expect(screen.getByLabelText("Source")).toHaveValue("nope");
  });

  it("loads the lists again when they change elsewhere, once shown", async () => {
    const api = fakeApi();
    const { user, push } = await openExtensions(api);
    await screen.findByRole("region", { name: /^Plugins/ });
    expect(api.plugins).toHaveBeenCalledTimes(1);

    push({ type: "extensions.updated", payload: {} });
    await waitFor(() => {
      expect(api.plugins).toHaveBeenCalledTimes(2);
    });
    await user.click(screen.getByRole("button", { name: "Connections" }));
    expect(screen.queryByRole("region", { name: /^Plugins/ })).not.toBeInTheDocument();
  });

  it("does not load the lists for a change before Extensions was opened", async () => {
    const api = fakeApi();
    const { push } = await openSettings(null, { api });

    push({ type: "extensions.updated", payload: {} });

    await Promise.resolve();
    expect(api.plugins).not.toHaveBeenCalled();
  });
});

describe("browse", () => {
  it("lists the offered plugins and installs one after a confirmation", async () => {
    const api = fakeApi();
    api.availablePlugins.mockResolvedValue([
      available(),
      available({ id: "superpowers@official", name: "superpowers", installed: true }),
    ]);
    const { user } = await openExtensions(api);

    await user.click(await screen.findByRole("button", { name: "Browse" }));
    const sheet = await screen.findByRole("dialog", { name: "Browse plugins" });
    expect(await within(sheet).findByText("Installed")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Details of pdf-viewer" }));

    const details = await screen.findByRole("dialog", { name: "pdf-viewer" });
    expect(within(details).getByText("View and annotate PDFs")).toBeInTheDocument();
    expect(within(details).getByText("./plugins/pdf-viewer")).toBeInTheDocument();
    expect(within(details).getByText("1.2.0")).toBeInTheDocument();
    expect(await within(details).findByText("Skills (2)")).toBeInTheDocument();
    expect(within(details).getByText("open, annotate")).toBeInTheDocument();
    expect(within(details).getByText("MCP servers (1)")).toBeInTheDocument();
    expect(within(details).queryByText(/Agents/)).not.toBeInTheDocument();
    expect(api.pluginDetails).toHaveBeenCalledWith("pdf-viewer@official");

    await user.click(within(details).getByRole("button", { name: "Install" }));
    const confirm = screen.getByRole("alertdialog", { name: "Install pdf-viewer?" });
    expect(confirm).toHaveTextContent("Plugins can run code on this Mac.");
    await user.click(within(confirm).getByRole("button", { name: "Install" }));

    expect(api.installPlugin).toHaveBeenCalledWith("pdf-viewer@official");
    expect(await screen.findByText("Installed pdf-viewer")).toBeInTheDocument();
    const back = await screen.findByRole("dialog", { name: "Browse plugins" });
    expect(within(back).getAllByText("Installed")).toHaveLength(2);
  });

  it("shows an installed plugin's details without Install, and goes back", async () => {
    const api = fakeApi();
    api.availablePlugins.mockResolvedValue([
      available({ installed: true, description: null, version: null }),
    ]);
    api.pluginDetails.mockResolvedValue(pluginDetails({ installed: true, components: null }));
    const { user } = await openExtensions(api);

    await user.click(await screen.findByRole("button", { name: "Browse" }));
    await user.click(await screen.findByRole("button", { name: "Details of pdf-viewer" }));
    const details = await screen.findByRole("dialog", { name: "pdf-viewer" });
    await waitFor(() => {
      expect(within(details).queryByText("Loading...")).not.toBeInTheDocument();
    });
    expect(within(details).queryByRole("button", { name: "Install" })).toBeNull();
    expect(within(details).queryByText("Version")).toBeNull();

    await user.click(within(details).getByRole("button", { name: "Done" }));
    expect(await screen.findByRole("dialog", { name: "Browse plugins" })).toBeInTheDocument();
  });

  it("keeps the details open when installing fails or is cancelled", async () => {
    const api = fakeApi();
    api.availablePlugins.mockResolvedValue([available()]);
    api.installPlugin.mockRejectedValue(new ApiError(502, "marketplace runs a command"));
    const { user } = await openExtensions(api);

    await user.click(await screen.findByRole("button", { name: "Browse" }));
    await user.click(await screen.findByRole("button", { name: "Details of pdf-viewer" }));
    await user.click(await screen.findByRole("button", { name: "Install" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    await user.click(screen.getByRole("button", { name: "Install" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Install" }),
    );

    expect(await screen.findByText("marketplace runs a command")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "pdf-viewer" })).toBeInTheDocument();
  });

  it("says when nothing is offered, and when the list or details cannot load", async () => {
    const api = fakeApi();
    api.availablePlugins
      .mockResolvedValueOnce([])
      .mockRejectedValueOnce(new ApiError(502, "no marketplaces"));
    const { user } = await openExtensions(api);

    await user.click(await screen.findByRole("button", { name: "Browse" }));
    expect(await screen.findByText("No plugins offered")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Done" }));
    await user.click(screen.getByRole("button", { name: "Browse" }));
    expect(await screen.findByText("no marketplaces")).toBeInTheDocument();
    expect(await screen.findByText("No plugins offered")).toBeInTheDocument();
  });

  it("keeps waiting for details that cannot load, and ignores late answers", async () => {
    const api = fakeApi();
    let list: (value: AvailablePlugin[]) => void = () => undefined;
    api.availablePlugins
      .mockReturnValueOnce(
        new Promise((resolve) => {
          list = resolve;
        }),
      )
      .mockResolvedValue([available()]);
    let details: (value: PluginDetails) => void = () => undefined;
    api.pluginDetails
      .mockRejectedValueOnce(new ApiError(404, "unknown plugin"))
      .mockReturnValueOnce(
        new Promise((resolve) => {
          details = resolve;
        }),
      );
    const { user } = await openExtensions(api);

    await user.click(await screen.findByRole("button", { name: "Browse" }));
    expect(screen.getByRole("dialog", { name: "Browse plugins" })).toHaveTextContent("Loading...");
    await user.click(screen.getByRole("button", { name: "Done" }));
    list([available({ name: "late" })]);
    await user.click(screen.getByRole("button", { name: "Browse" }));
    expect(screen.queryByText("late")).not.toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "Details of pdf-viewer" }));
    expect(await screen.findByText("unknown plugin")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "pdf-viewer" })).toHaveTextContent("Loading...");
    await user.click(screen.getByRole("button", { name: "Done" }));
    await user.click(await screen.findByRole("button", { name: "Details of pdf-viewer" }));
    await user.click(screen.getByRole("button", { name: "Done" }));
    details(pluginDetails());
    expect(await screen.findByRole("dialog", { name: "Browse plugins" })).toBeInTheDocument();
  });
});
