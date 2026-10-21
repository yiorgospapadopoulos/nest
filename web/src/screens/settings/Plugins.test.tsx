import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { AvailablePlugin, PluginDetails } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import {
  codexPlugins,
  configurationPage,
  engineSection,
  installedPlugin,
  marketplace,
  pluginDetails,
} from "../../test/fixtures.ts";
import { openSettings } from "../../test/settings.ts";

// Claude's and Codex's plugins in Settings > Configuration (B97, B102 item 31), which took
// them over from Extensions.

const openConfiguration = (api = fakeApi()) => openSettings("Configuration", { api });

async function openPlugins(api = fakeApi()) {
  const rendered = await openConfiguration(api);
  const claude = await screen.findByRole("region", { name: "Claude" });
  await rendered.user.click(within(claude).getByRole("button", { name: /^Plugins/ }));
  return rendered;
}

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

describe("claude plugins", () => {
  it("lists the installed plugins with their switches, folded until asked", async () => {
    const api = fakeApi();
    api.plugins.mockResolvedValue([
      installedPlugin(),
      installedPlugin({ id: "x@local", name: "x", marketplace: "local", version: null }),
    ]);
    const { user } = await openConfiguration(api);
    const claude = await screen.findByRole("region", { name: "Claude" });
    const fold = within(claude).getByRole("button", { name: /^Plugins/ });
    expect(fold).toHaveTextContent("Plugins1 installed");
    expect(fold).toHaveAttribute("aria-expanded", "false");
    expect(within(claude).getByRole("button", { name: "Marketplaces" })).toBeInTheDocument();

    await user.click(fold);

    expect(await within(claude).findByText("official, 4.1.0")).toBeInTheDocument();
    expect(within(claude).getByText("local")).toBeInTheDocument();
    expect(within(claude).getByRole("switch", { name: /superpowers/ })).toBeChecked();
    expect(within(claude).getByRole("button", { name: "Marketplaces 1" })).toBeInTheDocument();
    await user.click(fold);
    expect(within(claude).queryByText("local")).toBeNull();
  });

  it("says when no plugin is installed", async () => {
    const api = fakeApi();
    api.plugins.mockResolvedValueOnce([]);
    await openPlugins(api);
    expect(await screen.findByText("No plugins installed")).toBeInTheDocument();
  });

  it("waits for the list that cannot load", async () => {
    const api = fakeApi();
    api.plugins.mockRejectedValue(new ApiError(502, "claude plugin failed"));
    await openPlugins(api);

    expect(await screen.findByText("claude plugin failed")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Claude" })).toHaveTextContent("Loading...");
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
    const { user } = await openPlugins(api);
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
    const { user } = await openPlugins(api);

    await user.click(await screen.findByRole("button", { name: "Remove superpowers" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(api.uninstallPlugin).not.toHaveBeenCalled();
    api.plugins.mockResolvedValue([]);
    await user.click(screen.getByRole("button", { name: "Remove superpowers" }));
    const confirm = screen.getByRole("alertdialog", { name: "Remove superpowers?" });
    expect(confirm).toHaveTextContent("Claude Code uninstalls it.");
    await user.click(within(confirm).getByRole("button", { name: "Remove" }));

    expect(api.uninstallPlugin).toHaveBeenCalledWith("superpowers@official");
    expect(await screen.findByText("Removed superpowers")).toBeInTheDocument();
    expect(await screen.findByText("No plugins installed")).toBeInTheDocument();
  });

  it("says why a plugin could not be removed", async () => {
    const api = fakeApi();
    api.uninstallPlugin.mockRejectedValue(new ApiError(502, "uninstall failed"));
    const { user } = await openPlugins(api);

    await user.click(await screen.findByRole("button", { name: "Remove superpowers" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Remove" }),
    );

    expect(await screen.findByText("uninstall failed")).toBeInTheDocument();
    expect(api.plugins).toHaveBeenCalledTimes(1);
  });

  it("lists, adds and removes marketplaces", async () => {
    const api = fakeApi();
    api.marketplaces.mockResolvedValue([
      marketplace(),
      marketplace({ name: "mine", kind: "directory", source: null }),
    ]);
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: "Marketplaces" }));
    const sheet = screen.getByRole("dialog", { name: "Marketplaces" });
    expect(await within(sheet).findByText("anthropics/claude-plugins")).toBeInTheDocument();
    expect(within(sheet).getByText("mine")).toBeInTheDocument();

    await user.click(within(sheet).getByRole("button", { name: "Add marketplace" }));
    await user.click(defined(screen.getAllByRole("button", { name: "Close" }).at(-1)));
    await user.click(within(sheet).getByRole("button", { name: "Add marketplace" }));
    await user.type(screen.getByLabelText("Source"), "me/plugins");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(api.addMarketplace).toHaveBeenCalledWith("me/plugins");
    expect(await screen.findByText("Marketplace added")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Add marketplace" })).toBeNull();

    await user.click(within(sheet).getByRole("button", { name: "Remove official" }));
    await user.click(
      within(screen.getByRole("alertdialog", { name: "Remove official?" })).getByRole("button", {
        name: "Remove",
      }),
    );
    expect(api.removeMarketplace).toHaveBeenCalledWith("official");
    expect(await screen.findByText("Removed official")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Remove mine" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    await user.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog", { name: "Marketplaces" })).toBeNull();
  });

  it("waits for the marketplaces, and keeps the source when one cannot be added", async () => {
    const api = fakeApi();
    let markets: (value: ReturnType<typeof marketplace>[]) => void = () => undefined;
    api.marketplaces.mockReturnValueOnce(
      new Promise((resolve) => {
        markets = resolve;
      }),
    );
    api.addMarketplace.mockRejectedValue(new ApiError(502, "not a marketplace"));
    const { user } = await openConfiguration(api);
    await user.click(await screen.findByRole("button", { name: "Marketplaces" }));
    expect(screen.getByRole("dialog", { name: "Marketplaces" })).toHaveTextContent("Loading...");
    markets([marketplace()]);

    await user.click(await screen.findByRole("button", { name: "Add marketplace" }));
    await user.type(screen.getByLabelText("Source"), "nope");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(await screen.findByText("not a marketplace")).toBeInTheDocument();
    expect(screen.getByLabelText("Source")).toHaveValue("nope");
  });

  it("loads the lists again when they change elsewhere, once shown", async () => {
    const api = fakeApi();
    const { push } = await openPlugins(api);
    await screen.findByRole("switch", { name: /superpowers/ });
    expect(api.plugins).toHaveBeenCalledTimes(1);

    push({ type: "extensions.updated", payload: {} });
    await waitFor(() => {
      expect(api.plugins).toHaveBeenCalledTimes(2);
    });
  });

  it("does not load the lists for a change before they were shown", async () => {
    const api = fakeApi();
    const { push } = await openSettings(null, { api });

    push({ type: "extensions.updated", payload: {} });

    await Promise.resolve();
    expect(api.plugins).not.toHaveBeenCalled();
  });
});

describe("claude browse", () => {
  it("lists the offered plugins and installs one after a confirmation", async () => {
    const api = fakeApi();
    api.availablePlugins.mockResolvedValue([
      available(),
      available({ id: "superpowers@official", name: "superpowers", installed: true }),
    ]);
    const { user } = await openConfiguration(api);

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
    const { user } = await openConfiguration(api);

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
    const { user } = await openConfiguration(api);

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

  it("says when nothing is offered, and when the list cannot load", async () => {
    const api = fakeApi();
    api.availablePlugins
      .mockResolvedValueOnce([])
      .mockRejectedValueOnce(new ApiError(502, "no marketplaces"));
    const { user } = await openConfiguration(api);

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
    const { user } = await openConfiguration(api);

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

describe("codex plugins", () => {
  const codex = engineSection({
    id: "codex",
    name: "Codex",
    account: null,
    items: [{ kind: "plugins", count: 1, detail: null, path: null, folder: false }],
  });
  async function openCodex(api = fakeApi()) {
    api.configuration.mockResolvedValue(configurationPage({ engines: [engineSection(), codex] }));
    const rendered = await openConfiguration(api);
    const box = await screen.findByRole("region", { name: "Codex" });
    await rendered.user.click(within(box).getByRole("button", { name: /^Codex/ }));
    return { ...rendered, box };
  }

  it("lists Codex's own plugins and removes one", async () => {
    const api = fakeApi();
    const plain = { ...defined(codexPlugins().plugins[0]), id: "x@openai", name: "x" };
    api.codexPlugins.mockResolvedValue(
      codexPlugins({
        plugins: [
          ...codexPlugins().plugins,
          { ...plain, marketplace: "openai", description: null },
        ],
      }),
    );
    api.uninstallCodexPlugin.mockResolvedValue(
      codexPlugins({
        plugins: [{ ...defined(codexPlugins().plugins[0]), installed: false, description: null }],
      }),
    );
    const { user, box } = await openCodex(api);
    const fold = within(box).getByRole("button", { name: /^Plugins/ });
    expect(fold).toHaveTextContent("Codex's own · 1 installed");

    await user.click(fold);
    expect(await within(box).findByText("openai · GitHub tools")).toBeInTheDocument();
    expect(within(box).getByText("openai")).toBeInTheDocument();
    expect(api.codexPlugins).toHaveBeenCalledWith("");
    await user.click(within(box).getByRole("button", { name: "Remove github" }));

    expect(api.uninstallCodexPlugin).toHaveBeenCalledWith("github@openai");
    expect(await within(box).findByText("No plugins of Codex's own")).toBeInTheDocument();
  });

  it("keeps the list when a plugin cannot be removed, and ignores a late list", async () => {
    const api = fakeApi();
    let late: (value: ReturnType<typeof codexPlugins>) => void = () => undefined;
    api.codexPlugins
      .mockReturnValueOnce(
        new Promise((resolve) => {
          late = resolve;
        }),
      )
      .mockResolvedValue(codexPlugins());
    api.uninstallCodexPlugin.mockRejectedValue(new ApiError(502, "codex failed"));
    const { user, box } = await openCodex(api);
    const fold = within(box).getByRole("button", { name: /^Plugins/ });
    await user.click(fold);
    expect(within(box).getByText("Loading...")).toBeInTheDocument();
    await user.click(fold);
    late(codexPlugins({ plugins: [] }));
    await user.click(fold);

    await user.click(await within(box).findByRole("button", { name: "Remove github" }));
    expect(await screen.findByText("codex failed")).toBeInTheDocument();
    expect(within(box).getByRole("button", { name: "Remove github" })).toBeEnabled();
  });

  it("searches the offered plugins and installs one", async () => {
    const api = fakeApi();
    const offered = {
      ...defined(codexPlugins().plugins[0]),
      id: "slack@openai",
      name: "slack",
      installed: false,
    };
    api.codexPlugins.mockImplementation((query) =>
      Promise.resolve(
        codexPlugins({
          plugins: query === "zzz" ? [] : [...codexPlugins().plugins, offered],
        }),
      ),
    );
    const afterInstall = codexPlugins({
      plugins: [...codexPlugins().plugins, { ...offered, installed: true }],
    });
    api.installCodexPlugin.mockResolvedValue(afterInstall);
    const { user, box } = await openCodex(api);

    await user.click(within(box).getByRole("button", { name: "Browse" }));
    const sheet = screen.getByRole("dialog", { name: "Browse Codex's plugins" });
    expect(await within(sheet).findByText("slack")).toBeInTheDocument();
    expect(within(sheet).queryByText("github")).toBeNull();
    await user.type(within(sheet).getByLabelText("Search Codex's plugins"), "zzz");
    expect(await within(sheet).findByText("No plugins match")).toBeInTheDocument();
    expect(api.codexPlugins).toHaveBeenLastCalledWith("zzz");
    await user.clear(within(sheet).getByLabelText("Search Codex's plugins"));
    // From now on Codex lists it as installed.
    api.codexPlugins.mockResolvedValue(afterInstall);
    await user.click(await within(sheet).findByRole("button", { name: "Install slack" }));

    expect(api.installCodexPlugin).toHaveBeenCalledWith("slack@openai");
    expect(await within(sheet).findByText("The marketplaces offer no plugins")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Done" }));
    await user.click(within(box).getByRole("button", { name: /^Plugins/ }));
    expect(await within(box).findByText("slack")).toBeInTheDocument();
  });

  it("keeps the offered list when an install fails, and waits for a list that cannot load", async () => {
    const api = fakeApi();
    api.installCodexPlugin.mockRejectedValue(new ApiError(502, "cannot install"));
    api.codexPlugins
      .mockRejectedValueOnce(new ApiError(502, "codex is down"))
      .mockResolvedValue(
        codexPlugins({ plugins: [{ ...defined(codexPlugins().plugins[0]), installed: false }] }),
      );
    const { user, box } = await openCodex(api);
    await user.click(within(box).getByRole("button", { name: "Browse" }));
    const sheet = screen.getByRole("dialog", { name: "Browse Codex's plugins" });
    expect(await screen.findByText("codex is down")).toBeInTheDocument();
    expect(sheet).toHaveTextContent("Loading...");
    await user.type(within(sheet).getByLabelText("Search Codex's plugins"), "g");

    await user.click(await within(sheet).findByRole("button", { name: "Install github" }));
    expect(await screen.findByText("cannot install")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Install github" })).toBeInTheDocument();
  });

  it("lists, adds and removes Codex's marketplaces", async () => {
    const api = fakeApi();
    api.codexMarketplaces.mockResolvedValue([
      { name: "openai", path: null },
      { name: "mine", path: "/Users/me/market" },
    ]);
    api.addCodexMarketplace
      .mockRejectedValueOnce(new ApiError(422, "not a marketplace"))
      .mockResolvedValue([{ name: "new", path: null }]);
    api.removeCodexMarketplace
      .mockRejectedValueOnce(new ApiError(502, "busy"))
      .mockResolvedValue([]);
    const { user, box } = await openCodex(api);

    await user.click(within(box).getByRole("button", { name: "Marketplaces" }));
    const sheet = screen.getByRole("dialog", { name: "Codex's marketplaces" });
    expect(await within(sheet).findByText("/Users/me/market")).toBeInTheDocument();
    const field = within(sheet).getByLabelText("Marketplace source");
    expect(within(sheet).getByRole("button", { name: "Add" })).toBeDisabled();
    await user.type(field, " me/market ");
    await user.click(within(sheet).getByRole("button", { name: "Add" }));
    expect(api.addCodexMarketplace).toHaveBeenCalledWith("me/market");
    expect(await screen.findByText("not a marketplace")).toBeInTheDocument();
    expect(field).toHaveValue(" me/market ");
    await user.click(within(sheet).getByRole("button", { name: "Add" }));
    expect(await within(sheet).findByText("new")).toBeInTheDocument();
    expect(field).toHaveValue("");

    await user.click(within(sheet).getByRole("button", { name: "Remove new" }));
    expect(await screen.findByText("busy")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Remove new" }));
    await waitFor(() => {
      expect(within(sheet).queryByText("new")).toBeNull();
    });
    await user.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("waits for marketplaces that cannot load", async () => {
    const api = fakeApi();
    api.codexMarketplaces.mockRejectedValue(new ApiError(502, "no marketplaces"));
    const { user, box } = await openCodex(api);
    await user.click(within(box).getByRole("button", { name: "Marketplaces" }));

    expect(await screen.findByText("no marketplaces")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Done" }));
  });
});
