import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import { ACCOUNTS_CHANGED } from "../../api/events.ts";
import type { EngineAccount, GithubAccount } from "../../api/types.ts";
import {
  accountList,
  accountWindow,
  codexAccount,
  engineAccount,
  localModel,
} from "../../test/accounts.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { acpProvider, claudeProvider, codexProvider, github } from "../../test/fixtures.ts";
import { openSettings } from "../../test/settings.ts";

const openAccounts = (api = fakeApi()) => openSettings("Accounts", { api });
const section = (name: string) => screen.getByRole("region", { name });

/** The fake API with Claude's Personal (in use) and Work, and Codex's own login. */
function withAccounts(accounts: EngineAccount[] = accountList()) {
  const api = fakeApi();
  api.accounts.mockResolvedValue({ accounts });
  return api;
}

const checked = (engine: string) =>
  within(screen.getByRole("radiogroup", { name: `${engine} account in use` }))
    .getAllByRole("radio")
    .filter((radio) => radio.getAttribute("aria-checked") === "true")
    .map((radio) => radio.getAttribute("aria-label"));

describe("engine accounts (B98)", () => {
  it("lists each engine's accounts with their plan, login and every window", async () => {
    await openAccounts(withAccounts());

    const claude = await screen.findByRole("region", { name: "Claude" });
    await within(claude).findByText("Work");
    expect(within(claude).getByText("Max 20x · me@example.com")).toBeInTheDocument();
    expect(within(claude).getByText("Pro · me@work.example")).toBeInTheDocument();
    expect(within(claude).getAllByText("Signed in")).toHaveLength(2);
    expect(within(claude).getByRole("meter", { name: "Personal Weekly used" })).toHaveAttribute(
      "aria-valuenow",
      "81",
    );
    expect(within(claude).getByRole("meter", { name: "Work Weekly used" })).toHaveAttribute(
      "aria-valuenow",
      "42",
    );
    expect(checked("Claude")).toEqual(["Use Personal for Claude"]);
    // The email is the title, so the line under it is the plan alone.
    const codex = section("Codex");
    expect(within(codex).getByText("ChatGPT Plus")).toBeInTheDocument();
    expect(within(codex).getByRole("meter", { name: "me@example.com 30 day used" })).toBeVisible();
    expect(within(claude).queryByText(/Add .* account/)).toBeNull();
    expect(within(claude).queryByRole("button", { name: "Sign in" })).toBeNull();
  });

  it("moves the check to the account tapped", async () => {
    const api = withAccounts();
    const moved = accountList().map((a) =>
      a.provider === "claude" ? { ...a, active: a.id === "claude-work" } : a,
    );
    api.activateAccount.mockResolvedValue({ accounts: moved });
    const { user } = await openAccounts(api);

    await user.click(await screen.findByRole("radio", { name: "Use Work for Claude" }));

    expect(api.activateAccount).toHaveBeenCalledWith("claude-work");
    expect(checked("Claude")).toEqual(["Use Work for Claude"]);
    expect(checked("Codex")).toEqual(["Use me@example.com for Codex"]);
  });

  it("keeps the account in use when the Mac refuses the switch, and says why", async () => {
    const api = withAccounts();
    api.activateAccount.mockRejectedValue(new ApiError(409, "Work is not signed in"));
    const { user } = await openAccounts(api);

    await user.click(await screen.findByRole("radio", { name: "Use Work for Claude" }));

    expect(await screen.findByText("Work is not signed in")).toBeInTheDocument();
    expect(checked("Claude")).toEqual(["Use Personal for Claude"]);
  });

  it("does not move the check to a signed-out account", async () => {
    const accounts = accountList().map((a) =>
      a.id === "claude-work" ? { ...a, signed_in: false } : a,
    );
    const api = withAccounts(accounts);
    const { user } = await openAccounts(api);

    await user.click(await screen.findByRole("radio", { name: "Use Work for Claude" }));

    expect(api.activateAccount).not.toHaveBeenCalled();
    expect(checked("Claude")).toEqual(["Use Personal for Claude"]);
    expect(within(section("Claude")).getByText("Signed out")).toBeInTheDocument();
  });

  it("removes an added account only after a confirmation, and never the first", async () => {
    const api = withAccounts();
    api.removeAccount.mockResolvedValue({
      accounts: accountList().filter((a) => a.id !== "claude-work"),
    });
    const { user } = await openAccounts(api);

    await user.click(await screen.findByRole("button", { name: "Actions for Personal" }));
    const own = screen.getByRole("dialog", { name: "Actions for Personal" });
    expect(within(own).queryByRole("menuitem", { name: "Remove" })).toBeNull();
    expect(within(own).queryByRole("menuitem", { name: "Use this account" })).toBeNull();
    await user.click(within(own).getByRole("button", { name: "Cancel" }));

    await user.click(screen.getByRole("button", { name: "Actions for Work" }));
    await user.click(screen.getByRole("menuitem", { name: "Remove" }));
    const confirm = screen.getByRole("alertdialog", { name: "Remove Work?" });
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(api.removeAccount).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Actions for Work" }));
    await user.click(screen.getByRole("menuitem", { name: "Remove" }));
    await user.click(
      within(screen.getByRole("alertdialog", { name: "Remove Work?" })).getByRole("button", {
        name: "Remove",
      }),
    );

    expect(api.removeAccount).toHaveBeenCalledWith("claude-work");
    await waitFor(() => {
      expect(within(section("Claude")).queryByText("Work")).toBeNull();
    });
  });

  it("signs out of the first account after the Mac's warning, and renames", async () => {
    const api = withAccounts();
    api.signOutAccount.mockResolvedValue(engineAccount({ signed_in: false, limits: [] }));
    api.renameAccount.mockResolvedValue(engineAccount({ name: "Home", title: "Home" }));
    const { user } = await openAccounts(api);

    await user.click(await screen.findByRole("button", { name: "Actions for Personal" }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));
    const confirm = screen.getByRole("alertdialog", { name: "Sign out of Personal?" });
    expect(confirm).toHaveTextContent(
      "Claude Code on this Mac signs out too. Chats cannot run until you sign in again.",
    );
    await user.click(within(confirm).getByRole("button", { name: "Sign out" }));
    expect(api.signOutAccount).toHaveBeenCalledWith("claude-main");
    expect(await within(section("Claude")).findByText("Signed out")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Actions for Personal" }));
    await user.click(screen.getByRole("menuitem", { name: "Rename" }));
    const name = screen.getByLabelText("Account name");
    await user.clear(name);
    await user.type(name, "  Home ");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(api.renameAccount).toHaveBeenCalledWith("claude-main", "Home");
    expect(await within(section("Claude")).findByText("Home")).toBeInTheDocument();
  });

  it("follows accounts.changed", async () => {
    const { push } = await openAccounts(withAccounts());
    await within(await screen.findByRole("region", { name: "Claude" })).findByText("Work");

    const next = accountList().map((a) =>
      a.id === "claude-work"
        ? { ...a, active: true, limits: [accountWindow({ utilization: 0.5 })] }
        : { ...a, active: a.provider !== "claude" },
    );
    push({ type: ACCOUNTS_CHANGED, payload: { accounts: next } as never });

    expect(checked("Claude")).toEqual(["Use Work for Claude"]);
    expect(screen.getByRole("meter", { name: "Work 5 hour used" })).toHaveAttribute(
      "aria-valuenow",
      "50",
    );
  });

  it("says signing in is optional while local models run chats", async () => {
    const api = withAccounts([
      engineAccount({ signed_in: false, name: null, title: "Claude", email: null, plan: null }),
    ]);
    api.localModels.mockResolvedValue({
      models: [localModel()],
      engine: "claude",
      local_only: false,
    });
    await openAccounts(api);

    const claude = await screen.findByRole("region", { name: "Claude" });
    expect(await within(claude).findByText("Not signed in, optional")).toBeInTheDocument();
    expect(within(claude).queryByText(/Sign in to Claude on the Mac/)).toBeNull();
    expect(within(section("Codex")).getByText("Not signed in")).toBeInTheDocument();
  });
});

describe("banked resets (B98)", () => {
  const credit = {
    id: "c1",
    title: "Weekly reset",
    description: null,
    expires_at: "2026-11-20T12:00:00Z",
  };
  const withResets = () => {
    const api = withAccounts([
      engineAccount(),
      codexAccount({ banked_resets: { available: 1, credits: null } }),
    ]);
    api.bankedResets.mockResolvedValue({ available: 1, credits: [credit] });
    return api;
  };

  it("uses a reset only after a confirmation, then says what it did", async () => {
    const api = withResets();
    api.useBankedReset.mockResolvedValue({
      outcome: "reset",
      accounts: [engineAccount(), codexAccount()],
    });
    const { user } = await openAccounts(api);

    await user.click(await screen.findByRole("button", { name: "Banked resets 1" }));
    const sheet = screen.getByRole("dialog", { name: "Banked resets" });
    expect(await within(sheet).findByText("expires 20 Nov")).toBeInTheDocument();
    expect(api.bankedResets).toHaveBeenCalledWith("codex-main");

    await user.click(
      within(sheet).getByRole("button", { name: "Use Weekly reset on me@example.com" }),
    );
    const confirm = screen.getByRole("alertdialog", {
      name: "Use a banked reset on me@example.com?",
    });
    expect(confirm).toHaveTextContent("Its current Codex limits reset now.");
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(api.useBankedReset).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Use Weekly reset on me@example.com" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Use" }));

    expect(api.useBankedReset).toHaveBeenCalledWith("codex-main", "c1");
    expect(await screen.findByText("Limits reset")).toBeInTheDocument();
  });

  it("has none for Claude", async () => {
    await openAccounts(withResets());

    await screen.findByRole("button", { name: "Banked resets 1" });
    expect(within(section("Claude")).queryByText(/Banked resets/)).toBeNull();
  });
});

describe("Claude Code's limit reset (B161)", () => {
  it("shows for the accounts the daemon offers it on, and opens it after a confirmation", async () => {
    const api = withAccounts([
      engineAccount({ limit_reset: true }),
      engineAccount({ id: "claude-work", title: "Work", active: false, first: false }),
    ]);
    const { user } = await openAccounts(api);

    const claude = await screen.findByRole("region", { name: "Claude" });
    expect(await within(claude).findAllByText("Limit reset")).toHaveLength(1);
    expect(within(claude).queryByRole("button", { name: "Reset in Terminal for Work" })).toBeNull();

    await user.click(
      within(claude).getByRole("button", { name: "Reset in Terminal for Personal" }),
    );
    const confirm = screen.getByRole("alertdialog", { name: "Use the limit reset on Personal?" });
    expect(confirm).toHaveTextContent("opens in a terminal on your computer");
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(api.openLimitReset).not.toHaveBeenCalled();

    await user.click(
      within(claude).getByRole("button", { name: "Reset in Terminal for Personal" }),
    );
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Reset in Terminal" }),
    );
    expect(api.openLimitReset).toHaveBeenCalledWith("claude-main");
  });

  it("lists the per-model limits with the account's own", async () => {
    await openAccounts(
      withAccounts([
        engineAccount({
          limits: [
            accountWindow({ label: "Weekly", minutes: 10080, utilization: 0.25 }),
            accountWindow({
              label: "Fable weekly",
              scope: "Fable",
              minutes: 10080,
              utilization: 0.42,
            }),
          ],
        }),
      ]),
    );

    const claude = await screen.findByRole("region", { name: "Claude" });
    expect(
      await within(claude).findByRole("meter", { name: "Personal Fable weekly used" }),
    ).toHaveAttribute("aria-valuenow", "42");
  });
});

describe("github account", () => {
  it.each<[Partial<GithubAccount>, string, string]>([
    [{}, "octocat", "Signed in"],
    [{ state: "signed_out", login: null }, "GitHub", "Signed out"],
    [{ state: "unavailable", login: null }, "GitHub", "gh not installed"],
  ])("shows %o", async (overrides, label, state) => {
    const api = fakeApi();
    api.github.mockResolvedValue(github(overrides));
    await openAccounts(api);

    const box = await screen.findByRole("region", { name: "GitHub" });
    expect(within(box).getByText(label, { selector: ".slab" })).toBeInTheDocument();
    expect(within(box).getByText(state)).toBeInTheDocument();
  });

  it("checks again on request", async () => {
    const api = fakeApi();
    api.github.mockResolvedValue(github({ state: "signed_out", login: null }));
    let finish: (value: GithubAccount) => void = () => undefined;
    api.checkGithub.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { user } = await openAccounts(api);

    await user.click(await screen.findByRole("button", { name: "Check again" }));
    expect(screen.getByRole("button", { name: "Checking..." })).toBeDisabled();
    finish(github());

    expect(await screen.findByText("octocat")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Check again" })).toBeEnabled();
    });
  });

  it("says why checking failed", async () => {
    const api = fakeApi();
    api.checkGithub.mockRejectedValue(new ApiError(500, "gh broke"));
    const { user } = await openAccounts(api);

    await user.click(await screen.findByRole("button", { name: "Check again" }));

    expect(await screen.findByText("gh broke")).toBeInTheDocument();
    expect(screen.getByText("octocat")).toBeInTheDocument();
  });
});

describe("more engines (B107)", () => {
  const gemini = (signedIn: boolean) =>
    acpProvider({
      name: "gemini",
      display_name: "Gemini CLI",
      version: "0.65.0",
      signed_in: signedIn,
      sign_in: "api_key",
      login_command: null,
    });
  const engines = ({ geminiSignedIn = false, opencodeSignedIn = true } = {}) => ({
    providers: [
      claudeProvider(),
      codexProvider(),
      acpProvider({ signed_in: opencodeSignedIn }),
      gemini(geminiSignedIn),
      acpProvider({
        name: "cursor",
        display_name: "Cursor agent",
        version: null,
        git_guard: false,
        signed_in: null,
        state: "not_installed",
        state_detail: "Install Cursor agent yourself; Nest uses it from your PATH.",
        installable: false,
        sign_in: "terminal",
        login_command: "agent login",
      }),
    ],
  });
  const withEngines = (options?: Parameters<typeof engines>[0]) => {
    const api = fakeApi();
    api.providers.mockResolvedValue(engines(options));
    return api;
  };
  const GIT_WARNING =
    "Nest cannot block this engine's git commands, so it may commit or push on its own.";
  /** An engine's row in More engines. */
  const row = (name: string) => {
    const found = within(section("More engines")).getByText(name).closest(".srow");
    if (!(found instanceof HTMLElement)) throw new Error(`no row for ${name}`);
    return found;
  };

  it("lists every other engine as a row of one More engines section", async () => {
    await openAccounts(withEngines());

    await screen.findByRole("region", { name: "More engines" });
    expect(headingNames()).toEqual(["Claude", "Codex", "More engines", "Local models", "GitHub"]);

    const opencode = row("OpenCode");
    expect(opencode).toHaveTextContent("1.19.4");
    expect(within(opencode).getByText("Ready")).toBeInTheDocument();
    expect(within(opencode).queryByRole("button")).toBeNull();
    expect(within(opencode).queryByRole("img", { name: GIT_WARNING })).toBeNull();

    const key = row("Gemini CLI");
    expect(within(key).getByText("No key")).toBeInTheDocument();
    expect(within(key).getByRole("button", { name: "Add a Gemini CLI API key" })).toBeVisible();

    // Not installed, which the user does themselves: no action, no explanation.
    const cursor = row("Cursor agent");
    expect(within(cursor).getByRole("img", { name: GIT_WARNING })).toBeInTheDocument();
    expect(within(cursor).getByText("Not on PATH: install it yourself")).toBeInTheDocument();
    expect(within(cursor).queryByRole("button")).toBeNull();
    expect(section("More engines")).not.toHaveTextContent("from your PATH");
  });

  it("offers a signed-out OpenCode its sign-in command to copy", async () => {
    const { user } = await openAccounts(withEngines({ opencodeSignedIn: false }));
    await screen.findByRole("region", { name: "More engines" });

    const opencode = row("OpenCode");
    expect(within(opencode).getByText("Signed out")).toBeInTheDocument();
    const copy = within(opencode).getByRole("button", {
      name: "Copy the OpenCode sign-in command",
    });
    expect(copy).toHaveTextContent("Copy sign-in command");
    const written = vi.spyOn(navigator.clipboard, "writeText");
    await user.click(copy);

    expect(written).toHaveBeenCalledWith("opencode auth login");
  });

  it("adds a pasted key, then removes it", async () => {
    const api = withEngines();
    // The Mac checks a saved key and lists Gemini as signed in, until it is removed.
    api.saveEngineKey.mockImplementation(() => {
      api.providers.mockResolvedValue(engines({ geminiSignedIn: true }));
      return Promise.resolve({});
    });
    api.removeEngineKey.mockImplementation(() => {
      api.providers.mockResolvedValue(engines());
      return Promise.resolve({});
    });
    const { user } = await openAccounts(api);
    await screen.findByRole("region", { name: "More engines" });

    await user.click(within(row("Gemini CLI")).getByRole("button", { name: /Add a Gemini/ }));
    const field = screen.getByLabelText("Gemini CLI API key");
    expect(field).toHaveAttribute("type", "password");
    await user.type(field, "AIza-test{Enter}");

    expect(api.saveEngineKey).toHaveBeenCalledWith("gemini-main", "AIza-test");
    await waitFor(() => {
      expect(within(row("Gemini CLI")).getByText("Ready")).toBeInTheDocument();
    });
    await user.click(
      within(row("Gemini CLI")).getByRole("button", { name: "Remove the Gemini CLI API key" }),
    );
    expect(api.removeEngineKey).toHaveBeenCalledWith("gemini-main");
    expect(await within(row("Gemini CLI")).findByText("No key")).toBeInTheDocument();
  });

  it("installs an engine again after a failed install", async () => {
    const api = fakeApi();
    api.providers.mockResolvedValue({
      providers: [
        claudeProvider(),
        acpProvider({
          signed_in: null,
          state: "install_failed",
          state_detail: "npm could not be reached",
        }),
      ],
    });
    const { user } = await openAccounts(api);
    await screen.findByRole("region", { name: "More engines" });

    const opencode = row("OpenCode");
    expect(within(opencode).getByText("Install failed")).toBeInTheDocument();
    expect(section("More engines")).toHaveTextContent("npm could not be reached");
    const install = within(opencode).getByRole("button", { name: "Install OpenCode" });
    expect(install).toHaveTextContent("Install again");
    await user.click(install);

    expect(api.installEngine).toHaveBeenCalledWith("opencode");
  });
});

/** The section titles as a screen reader hears them, without the hidden marks. */
function headingNames(): string[] {
  return screen.getAllByRole("heading", { level: 2 }).map((h) =>
    [...h.childNodes]
      .filter((n) => !(n instanceof HTMLElement && n.getAttribute("aria-hidden") === "true"))
      .map((n) => n.textContent)
      .join(""),
  );
}
