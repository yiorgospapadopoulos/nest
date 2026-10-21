import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { GithubAccount } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { account, claudeAccount, codexAccount, github } from "../../test/fixtures.ts";
import { openSettings } from "../../test/settings.ts";

const openAccounts = (api = fakeApi()) => openSettings("Accounts", { api });
const section = (name: string) => screen.getByRole("region", { name });

describe("claude account", () => {
  it("shows the name, plan and the email only when asked", async () => {
    const { user } = await openAccounts();

    const claude = await screen.findByRole("region", { name: "Claude" });
    expect(await within(claude).findByText("Giorgos")).toBeInTheDocument();
    expect(within(claude).getByText("Signed in")).toBeInTheDocument();
    expect(within(claude).getByText("max")).toBeInTheDocument();
    expect(within(claude).queryByText("me@example.com")).not.toBeInTheDocument();

    await user.click(within(claude).getByRole("button", { name: "Show email" }));

    expect(within(claude).getByText("me@example.com")).toBeInTheDocument();
  });

  it("falls back when the name, plan and email are unknown", async () => {
    const api = fakeApi();
    api.account.mockResolvedValue(account({ display_name: null }));
    api.claudeAccount.mockResolvedValue(claudeAccount({ plan: null, email: null }));
    await openAccounts(api);

    const claude = section("Claude");
    expect(await within(claude).findByText("Claude account")).toBeInTheDocument();
    expect(within(claude).queryByText("Plan")).toBeNull();
    expect(within(claude).queryByRole("button", { name: "Show email" })).toBeNull();
  });

  it("signs out after a confirmation", async () => {
    const api = fakeApi();
    const { user } = await openAccounts(api);

    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(api.claudeLogout).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    const confirm = screen.getByRole("alertdialog", { name: "Sign out of Claude?" });
    await user.click(within(confirm).getByRole("button", { name: "Sign out" }));

    expect(api.claudeLogout).toHaveBeenCalled();
    expect(await screen.findByText("Not signed in")).toBeInTheDocument();
  });

  it("keeps the account when signing out fails", async () => {
    const api = fakeApi();
    api.claudeLogout.mockRejectedValue(new ApiError(502, "claude auth logout failed"));
    const { user } = await openAccounts(api);

    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Sign out" }),
    );

    expect(await screen.findByText("claude auth logout failed")).toBeInTheDocument();
    expect(within(section("Claude")).getByText("Signed in")).toBeInTheDocument();
  });

  it("signs in on the Mac and follows the account.claude event", async () => {
    const api = fakeApi();
    api.claudeAccount.mockResolvedValue(
      claudeAccount({ signed_in: false, email: null, plan: null }),
    );
    const { user, push } = await openAccounts(api);

    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(api.claudeLogin).toHaveBeenCalled();
    expect(
      await screen.findByText("Finish signing in in the browser on your Mac"),
    ).toBeInTheDocument();

    push({
      type: "account.claude",
      payload: { ...claudeAccount({ signed_in: false }), error: "The browser was closed" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("The browser was closed");

    push({ type: "account.claude", payload: { ...claudeAccount(), error: null } });
    expect(within(section("Claude")).getByText("Signed in")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says why signing in could not start", async () => {
    const api = fakeApi();
    api.claudeAccount.mockResolvedValue(claudeAccount({ signed_in: false }));
    api.claudeLogin.mockRejectedValue(new ApiError(409, "a sign-in is already running"));
    const { user } = await openAccounts(api);

    await user.click(await screen.findByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("a sign-in is already running")).toBeInTheDocument();
  });

  it("waits for the Mac", async () => {
    const api = fakeApi();
    api.claudeAccount.mockReturnValue(new Promise(() => undefined));
    api.github.mockReturnValue(new Promise(() => undefined));
    await openAccounts(api);

    expect(section("Claude")).toHaveTextContent("Loading...");
    expect(section("GitHub")).toHaveTextContent("Loading...");
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

describe("codex account", () => {
  it("shows the email, plan and status, between Claude and GitHub", async () => {
    await openAccounts();

    const codex = await screen.findByRole("region", { name: "Codex" });
    expect(await within(codex).findByText("me@example.com")).toBeInTheDocument();
    expect(within(codex).getByText("ChatGPT Plus")).toBeInTheDocument();
    expect(within(codex).getByText("Signed in")).toHaveClass("sst", "ok");
    const names = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(names).toEqual(["Claude", "Codex", "GitHub"]);
  });

  it("signs out after a confirmation and follows the account.codex event", async () => {
    const api = fakeApi();
    const { user, push } = await openAccounts(api);
    const codex = await screen.findByRole("region", { name: "Codex" });

    await user.click(await within(codex).findByRole("button", { name: "Sign out of Codex" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(api.codexLogout).not.toHaveBeenCalled();
    await user.click(within(codex).getByRole("button", { name: "Sign out of Codex" }));
    const confirm = screen.getByRole("alertdialog", { name: "Sign out of Codex?" });
    expect(confirm).toHaveTextContent(
      "Codex on this Mac signs out too. Codex chats cannot run until you sign in again.",
    );
    await user.click(within(confirm).getByRole("button", { name: "Sign out" }));

    expect(api.codexLogout).toHaveBeenCalled();
    expect(await within(codex).findByText("Signed out")).toHaveClass("sst", "wait");
    expect(within(codex).getByText("Codex", { selector: ".slab > span" })).toBeInTheDocument();
    expect(
      within(codex).getByText("Sign in to Codex on the Mac, in Settings > Accounts."),
    ).toBeVisible();
    expect(within(codex).queryByRole("button", { name: "Sign out of Codex" })).toBeNull();

    push({ type: "account.codex", payload: { ...codexAccount({ email: "" }) } });
    expect(within(codex).getByText("Signed in")).toBeInTheDocument();
    expect(within(codex).getByText("Codex", { selector: ".slab > span" })).toBeInTheDocument();
  });

  it("says when Codex could not be asked, and why", async () => {
    const api = fakeApi();
    api.codexAccount.mockResolvedValue(
      codexAccount({ signed_in: null, email: null, plan: null, error: "codex is not installed" }),
    );
    await openAccounts(api);
    const codex = await screen.findByRole("region", { name: "Codex" });

    expect(await within(codex).findByText("Not checked")).toBeInTheDocument();
    expect(within(codex).getByRole("alert")).toHaveTextContent("codex is not installed");
  });

  it("waits for the Mac", async () => {
    const api = fakeApi();
    api.codexAccount.mockReturnValue(new Promise(() => undefined));
    await openAccounts(api);

    expect(section("Codex")).toHaveTextContent("Loading...");
  });
});
