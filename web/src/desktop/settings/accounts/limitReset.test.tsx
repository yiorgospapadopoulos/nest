// B161: Claude's per-model limits in the usage popover and Settings, never in the chip
// itself, and Claude Code's limit reset, opened in a terminal only after a confirmation.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { accountWindow, codexAccount, engineAccount } from "../../../test/accounts.ts";
import { fakeApi } from "../../../test/fakeApi.ts";
import { socketFactory } from "../../../test/fakeSocket.ts";
import { memoryStorage } from "../../../test/render.tsx";
import { browserBridge } from "../../bridge.ts";
import { DesktopApp } from "../../DesktopApp.tsx";

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {
      return undefined;
    }
    unobserve() {
      return undefined;
    }
    disconnect() {
      return undefined;
    }
  };
});

const FABLE = accountWindow({
  label: "Fable weekly",
  scope: "Fable",
  minutes: 10080,
  utilization: 0.42,
});

function withFable(limitReset: boolean) {
  const api = fakeApi();
  const claude = engineAccount({
    limits: [accountWindow({ label: "Weekly", minutes: 10080, utilization: 0.25 }), FABLE],
    limit_reset: limitReset,
  });
  api.accounts.mockResolvedValue({ accounts: [claude, codexAccount()] });
  const storage = memoryStorage();
  render(
    <DesktopApp
      bridge={browserBridge({ search: "" }, null)}
      api={api}
      connect={socketFactory().connect}
      location={{ protocol: "http:", host: "127.0.0.1:41053" }}
      storage={() => storage}
    />,
  );
  return api;
}

async function openAccounts() {
  fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
  const pages = screen.getByRole("navigation", { name: "Settings pages" });
  fireEvent.click(within(pages).getByRole("button", { name: "Accounts" }));
}

describe("per-model limits", () => {
  it("show in the popover and Settings, while the chip keeps the account's own", async () => {
    withFable(false);

    const chip = await screen.findByRole("button", { name: /^Usage: Claude · Personal/ });
    expect(chip).not.toHaveAccessibleName(/Fable/);
    expect(chip).toHaveTextContent("25%");
    expect(chip).not.toHaveTextContent("42%");

    fireEvent.click(chip);
    const popover = await screen.findByRole("dialog", { name: "Usage" });
    expect(within(popover).getByText("Weekly")).toBeInTheDocument();
    expect(within(popover).getByText("Fable weekly")).toBeInTheDocument();
    expect(within(popover).getByText("42%")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });

    await openAccounts();
    expect(await screen.findByText("Fable weekly 42%")).toBeInTheDocument();
    expect(screen.queryByText("Limit reset")).toBeNull();
  });
});

describe("Claude Code's limit reset", () => {
  it("opens the terminal only after the confirmation", async () => {
    const api = withFable(true);
    await openAccounts();

    fireEvent.click(await screen.findByRole("button", { name: "Reset in Terminal for Personal" }));
    const confirm = screen.getByRole("alertdialog", {
      name: "Use the limit reset on Personal?",
    });
    expect(confirm).toHaveTextContent("uses this account's limit reset if it has one");
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(api.openLimitReset).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Reset in Terminal for Personal" }));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Reset in Terminal" }),
    );

    expect(api.openLimitReset).toHaveBeenCalledWith("claude-main");
    expect(await screen.findByText("Claude Code opened in a terminal")).toBeInTheDocument();
    expect(api.useBankedReset).not.toHaveBeenCalled();
  });
});
