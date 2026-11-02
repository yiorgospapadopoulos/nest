import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { accountWindow, codexAccount, engineAccount } from "../../test/accounts.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { repo } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

// The Chats header's usage (B116 option A): the checked accounts' shortest windows, a tap
// away from Settings > Usage.

describe("Chats header usage", () => {
  it("shows the accounts in use and opens Settings > Usage", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("todo-ui")]);
    api.accounts.mockResolvedValue({
      accounts: [
        engineAccount({ limits: [accountWindow({ utilization: 0.63 })] }),
        codexAccount({ limits: [accountWindow({ utilization: 0.01 })] }),
      ],
    });
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));

    const usage = await screen.findByRole("button", { name: "Usage: Claude 63% 5h, Codex 1% 5h" });
    await user.click(usage);
    expect(await screen.findByRole("heading", { name: "Usage" })).toBeInTheDocument();
  });

  it("shows nothing before any account reported a window", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("todo-ui")]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await screen.findByRole("button", { name: "Project: todo-ui" });
    expect(api.accounts).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /^Usage:/ })).not.toBeInTheDocument();
  });
});
