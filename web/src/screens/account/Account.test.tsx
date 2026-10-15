import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { UsageLimits } from "../../api/types.ts";
import { STORAGE_KEY } from "../../appearance/appearance.ts";
import { RESTART_POLL_MS, RESTART_POLLS } from "../../store/actions.ts";
import { StoreProvider } from "../../store/StoreProvider.tsx";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { connector, month } from "../../test/fixtures.ts";
import { memoryStorage, renderApp } from "../../test/render.tsx";
import { UsageCalendar } from "./UsageCalendar.tsx";

async function openAccount(api = fakeApi(), storage = memoryStorage()) {
  const rendered = await renderApp({ api, storage });
  await rendered.user.click(screen.getByRole("tab", { name: "Account" }));
  return rendered;
}

describe("usage", () => {
  it("shows the limit windows and this month", async () => {
    const api = fakeApi();
    const resets = new Date();
    resets.setHours(23, 30, 0, 0);
    api.usageLimits.mockResolvedValue({
      five_hour: { utilization: 0.3, resets_at: resets.toISOString(), updated_at: "x" },
      seven_day: null,
    });
    await openAccount(api);

    const meter = await screen.findByRole("meter", { name: "5 hour window used" });
    expect(meter).toHaveAttribute("aria-valuenow", "30");
    expect(screen.getByText("Resets 23:30")).toBeInTheDocument();
    expect(screen.getByText("Not reported yet")).toBeInTheDocument();
    expect(await screen.findByText("2.4M")).toBeInTheDocument();
    expect(screen.getByText("This month")).toBeInTheDocument();
  });

  it("says when each window was reported and dims numbers older than 10 minutes", async () => {
    const api = fakeApi();
    const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000);
    const clock = (at: Date) =>
      at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    const fresh = minutesAgo(2);
    const old = minutesAgo(11);
    api.usageLimits.mockResolvedValue({
      five_hour: { utilization: 0.3, resets_at: null, updated_at: fresh.toISOString() },
      seven_day: { utilization: 0.1, resets_at: null, updated_at: old.toISOString() },
    });
    await openAccount(api);

    const recent = await screen.findByText(`as of ${clock(fresh)}`);
    const stale = screen.getByText(`as of ${clock(old)}`);
    expect(recent).not.toHaveClass("stale");
    expect(stale).toHaveClass("stale");
    expect(stale).toHaveAttribute("title", "More than 10 minutes old");
  });

  it("refreshes the windows on request", async () => {
    const api = fakeApi();
    let finish: (value: UsageLimits) => void = () => undefined;
    api.refreshUsage.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { user } = await openAccount(api);
    await screen.findByRole("meter", { name: "5 hour window used" });

    await user.click(screen.getByRole("button", { name: "Refresh usage" }));
    expect(screen.getByRole("button", { name: "Refresh usage" })).toBeDisabled();
    act(() => {
      finish({
        five_hour: { utilization: 0.8, resets_at: null, updated_at: new Date().toISOString() },
        seven_day: null,
      });
    });

    await waitFor(() => {
      expect(screen.getByRole("meter", { name: "5 hour window used" })).toHaveAttribute(
        "aria-valuenow",
        "80",
      );
    });
    expect(screen.getByRole("button", { name: "Refresh usage" })).toBeEnabled();
  });

  it("explains a refresh that came too soon, and other failures", async () => {
    const api = fakeApi();
    api.refreshUsage
      .mockRejectedValueOnce(new ApiError(429, "usage was refreshed moments ago"))
      .mockRejectedValueOnce(new ApiError(502, "Claude did not report the usage limits"));
    const { user } = await openAccount(api);
    const button = await screen.findByRole("button", { name: "Refresh usage" });

    await user.click(button);
    expect(await screen.findByText("Usage was refreshed moments ago")).toBeInTheDocument();
    await user.click(button);
    expect(await screen.findByText("Claude did not report the usage limits")).toBeInTheDocument();
  });

  it("toasts when account data cannot load", async () => {
    const api = fakeApi();
    api.connectors.mockRejectedValue(new ApiError(500, "registry broke"));
    await openAccount(api);

    expect(await screen.findByText("registry broke")).toBeInTheDocument();
    const connectors = screen.getByRole("region", { name: "Connectors" });
    expect(within(connectors).getByText("Loading...")).toBeInTheDocument();
  });

  it("updates the limits live", async () => {
    const { push } = await openAccount();
    await screen.findByRole("meter", { name: "5 hour window used" });

    push({
      id: 2,
      type: "usage.updated",
      payload: { five_hour: null, seven_day: { utilization: 0.5, resets_at: null } },
    });

    expect(screen.getByRole("meter", { name: "Weekly used" })).toHaveAttribute(
      "aria-valuenow",
      "50",
    );
    // The event left the 5 hour window out: its last report stays.
    expect(screen.getByRole("meter", { name: "5 hour window used" })).toHaveAttribute(
      "aria-valuenow",
      "30",
    );
    expect(screen.getAllByText("Reset time unknown")).toHaveLength(2);
  });
});

describe("usage calendar", () => {
  function renderCalendar(today: Date, api = fakeApi()) {
    const sockets = socketFactory();
    render(
      <StoreProvider
        api={api}
        connect={sockets.connect}
        location={{ protocol: "http:", host: "x" }}
      >
        <UsageCalendar today={today} />
      </StoreProvider>,
    );
    return api;
  }

  it("shows each day's tokens, marks today and leaves the future empty", async () => {
    renderCalendar(new Date(2026, 9, 2, 12));

    const first = await screen.findByRole("button", {
      name: /Thu 1 Oct: 1,200,000 tokens, 3 sessions/,
    });
    expect(first).toHaveClass("hi");
    expect(screen.getByRole("button", { name: /Fri 2 Oct: 300 tokens, 1 session$/ })).toHaveClass(
      "today",
    );
    expect(screen.queryByRole("button", { name: /3 Oct/ })).not.toBeInTheDocument();
    expect(screen.getByText("October 2026")).toBeInTheDocument();
  });

  it("explains a selected day and clears it on a second tap", async () => {
    renderCalendar(new Date(2026, 9, 6, 12));
    const day = await screen.findByRole("button", { name: /Sat 3 Oct/ });

    day.click();
    await waitFor(() => {
      expect(day).toHaveAttribute("aria-pressed", "true");
    });
    expect(screen.getByText("No sessions")).toBeInTheDocument();
    day.click();
    await waitFor(() => {
      expect(screen.getByText("Tap a day for its tokens and sessions.")).toBeInTheDocument();
    });
  });

  it("moves between months, up to eleven back", async () => {
    const api = renderCalendar(new Date(2026, 9, 6, 12));
    await screen.findByRole("button", { name: /Thu 1 Oct/ });
    const previous = screen.getByRole("button", { name: "Previous month" });
    const next = screen.getByRole("button", { name: "Next month" });
    expect(next).toBeDisabled();

    previous.click();
    expect(await screen.findByText("September 2026", { selector: ".ulbl" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /30 Sept/ })).toBeInTheDocument();
    for (let i = 0; i < 10; i++) previous.click();
    await waitFor(() => {
      expect(previous).toBeDisabled();
    });
    expect(screen.getByText("November 2025", { selector: "b" })).toBeInTheDocument();
    next.click();
    await waitFor(() => {
      expect(api.usageMonth).toHaveBeenLastCalledWith(2025, 12);
    });
  });

  it("ignores a month that arrives after moving on", async () => {
    const api = fakeApi();
    let slow: (value: ReturnType<typeof month>) => void = () => undefined;
    api.usageMonth.mockReturnValueOnce(
      new Promise((resolve) => {
        slow = resolve;
      }),
    );
    renderCalendar(new Date(2026, 9, 6, 12), api);

    screen.getByRole("button", { name: "Previous month" }).click();
    await screen.findByRole("button", { name: /30 Sept/ });
    slow(month(2026, 10));
    await Promise.resolve();
    expect(screen.queryByRole("button", { name: /Oct/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /30 Sept/ })).toBeInTheDocument();
  });
});

describe("connectors", () => {
  it("groups connectors with status and sign-in hints", async () => {
    const api = fakeApi();
    api.connectors.mockResolvedValue([
      connector(),
      connector({ name: "claude.ai Slack", display_name: "Slack", status: "needs-auth" }),
      connector({
        name: "plugin:x:github",
        display_name: "github",
        group: "plugin",
        status: "needs-auth",
        manage_hint: "claude_code",
      }),
      connector({
        name: "linear",
        display_name: "linear",
        group: "local",
        status: "failed",
        error: "spawn ENOENT",
        manage_hint: "claude_code",
      }),
      connector({
        name: "odd",
        display_name: "odd",
        group: "local",
        status: "disabled",
        manage_hint: "claude_code",
      }),
      connector({
        name: "slow",
        display_name: "slow",
        group: "local",
        status: "pending",
        manage_hint: "claude_code",
      }),
    ]);
    const { push, user } = await openAccount(api);

    const aiToggle = await screen.findByRole("button", { name: /claude\.ai connectors/ });
    const localToggle = screen.getByRole("button", { name: /Plugins and local servers/ });
    // Closed by default, with a count and what needs the user.
    expect(aiToggle).toHaveAttribute("aria-expanded", "false");
    expect(localToggle).toHaveAttribute("aria-expanded", "false");
    expect(aiToggle).toHaveTextContent("claude.ai connectors1 needs attention2");
    expect(localToggle).toHaveTextContent("Plugins and local servers2 need attention4");
    expect(within(aiToggle).getByText("1 needs attention").parentElement).toHaveClass("s-wait");
    expect(within(localToggle).getByText("2 need attention").parentElement).toHaveClass("s-fail");
    expect(screen.queryByText("Gmail")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /claude\.ai connectors/ })).toBeNull();

    await user.click(aiToggle);
    expect(aiToggle).toHaveAttribute("aria-expanded", "true");
    const ai = screen.getByRole("region", { name: /claude\.ai connectors/ });
    expect(aiToggle).toHaveAttribute("aria-controls", ai.id);
    expect(within(ai).getByText("Gmail")).toBeInTheDocument();
    expect(within(ai).getByText("Sign in on claude.ai")).toBeInTheDocument();
    expect(screen.queryByText("spawn ENOENT")).not.toBeInTheDocument();

    await user.click(localToggle);
    const local = screen.getByRole("region", { name: /Plugins and local servers/ });
    expect(within(local).getAllByText("Set up with /mcp in Claude Code")).toHaveLength(3);
    expect(within(local).getByText("spawn ENOENT")).toBeInTheDocument();
    expect(within(local).getByText("disabled")).toBeInTheDocument();
    expect(within(local).getByText("Connecting")).toBeInTheDocument();

    await user.click(aiToggle);
    expect(aiToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Gmail")).not.toBeInTheDocument();

    push({ id: 3, type: "connectors.updated", payload: { connectors: [] } });
    expect(screen.getByText(/None reported yet/)).toBeInTheDocument();
  });

  it("shows no attention hint when every connector in a group is fine", async () => {
    const api = fakeApi();
    api.connectors.mockResolvedValue([connector()]);
    await openAccount(api);

    const toggle = await screen.findByRole("button", { name: /claude\.ai connectors/ });
    expect(toggle).toHaveTextContent(/^claude\.ai connectors1$/);
    expect(screen.queryByRole("button", { name: /Plugins and local servers/ })).toBeNull();
  });
});

describe("appearance", () => {
  afterEach(() => {
    for (const name of ["data-theme", "data-accent", "data-bubble", "data-glass"]) {
      document.documentElement.removeAttribute(name);
    }
  });

  it("applies and remembers theme, accent, bubble and wallpaper", async () => {
    const storage = memoryStorage();
    const { user } = await openAccount(fakeApi(), storage);
    const root = document.documentElement;

    await user.click(screen.getByRole("button", { name: "Dark" }));
    await user.click(screen.getByRole("button", { name: "Ocean" }));
    await user.click(screen.getByRole("button", { name: "Neutral" }));
    await user.click(screen.getByRole("button", { name: "Sky" }));

    expect(root).toHaveAttribute("data-theme", "dark");
    expect(root).toHaveAttribute("data-accent", "ocean");
    expect(root).toHaveAttribute("data-bubble", "neutral");
    expect(document.querySelector(".wall")).toHaveClass("wallpaper-sky");
    expect(screen.getByRole("button", { name: "Ocean" })).toHaveAttribute("aria-pressed", "true");
    expect(JSON.parse(storage.getItem(STORAGE_KEY) ?? "")).toEqual({
      theme: "dark",
      accent: "ocean",
      bubble: "neutral",
      wallpaper: "sky",
      glass: "clear",
    });

    await user.click(screen.getByRole("button", { name: "Auto" }));
    await user.click(screen.getByRole("button", { name: "Graphite" }));
    await user.click(screen.getByRole("button", { name: "Accent" }));
    expect(root).not.toHaveAttribute("data-theme");
    expect(root).not.toHaveAttribute("data-accent");
    expect(root).not.toHaveAttribute("data-bubble");
  });

  it("switches the glass theme at once, previews every theme and describes the chosen one", async () => {
    const storage = memoryStorage();
    const { user } = await openAccount(fakeApi(), storage);
    const root = document.documentElement;
    const group = screen.getByRole("group", { name: "Glass" });
    const choices = within(group).getAllByRole("button");

    expect(choices.map((choice) => choice.textContent)).toEqual([
      "Clear",
      "Frosted",
      "Smoke",
      "Blue Grey",
      "Deep",
    ]);
    expect(
      choices.map((choice) => choice.querySelector("[data-glass]")?.getAttribute("data-glass")),
    ).toEqual(["clear", "frosted", "smoke", "bluegrey", "deep"]);
    expect(root).not.toHaveAttribute("data-glass");
    expect(group).toHaveAccessibleDescription(/barely tinted/i);

    await user.click(within(group).getByRole("button", { name: "Smoke" }));

    expect(root).toHaveAttribute("data-glass", "smoke");
    expect(within(group).getByRole("button", { name: "Smoke" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(group).getByRole("button", { name: "Clear" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(group).toHaveAccessibleDescription(/smoked glass/i);
    expect(JSON.parse(storage.getItem(STORAGE_KEY) ?? "")).toMatchObject({ glass: "smoke" });

    await user.click(within(group).getByRole("button", { name: "Clear" }));
    expect(root).not.toHaveAttribute("data-glass");
  });

  it("restores the saved glass theme on start", async () => {
    const storage = memoryStorage();
    storage.setItem(STORAGE_KEY, JSON.stringify({ glass: "frosted" }));

    await renderApp({ storage });

    expect(document.documentElement).toHaveAttribute("data-glass", "frosted");
  });
});

describe("restart", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const restartButton = () => screen.getByRole("button", { name: /^Restart/ });

  /** Confirms the restart with fake timers, so the waits between checks are in the test's hands. */
  async function confirmRestart(user: Awaited<ReturnType<typeof openAccount>>["user"]) {
    await user.click(screen.getByRole("button", { name: "Restart Nest" }));
    const dialog = screen.getByRole("alertdialog", { name: "Restart Nest?" });
    const reload = vi.fn();
    vi.stubGlobal("location", { pathname: window.location.pathname, reload });
    vi.useFakeTimers();
    fireEvent.click(within(dialog).getByRole("button", { name: "Restart" }));
    await act(async () => {
      await Promise.resolve();
    });
    return reload;
  }

  const wait = async (ms: number) => {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  };

  it("sits at the very bottom and asks first", async () => {
    const api = fakeApi();
    const { user } = await openAccount(api);

    const sections = screen.getAllByRole("region");
    expect(sections.at(-1)).toHaveAccessibleName("Restart Nest");
    await user.click(screen.getByRole("button", { name: "Restart Nest" }));
    const dialog = screen.getByRole("alertdialog", { name: "Restart Nest?" });
    expect(dialog).toHaveTextContent(/Running turns are interrupted/);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(api.restartService).not.toHaveBeenCalled();
  });

  it("restarts Nest and reloads the page once it answers again", async () => {
    const api = fakeApi();
    api.health
      .mockRejectedValueOnce(new ApiError(502, "Bad gateway"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const { user } = await openAccount(api);

    const reload = await confirmRestart(user);

    expect(api.restartService).toHaveBeenCalledOnce();
    expect(restartButton()).toHaveTextContent("Restarting...");
    expect(restartButton()).toBeDisabled();
    expect(api.health).not.toHaveBeenCalled();
    await wait(RESTART_POLL_MS);
    expect(api.health).toHaveBeenCalledTimes(1);
    await wait(RESTART_POLL_MS);
    expect(api.health).toHaveBeenCalledTimes(2);
    expect(reload).not.toHaveBeenCalled();
    await wait(RESTART_POLL_MS);

    expect(api.health).toHaveBeenCalledTimes(3);
    expect(reload).toHaveBeenCalledOnce();
    // No error toast for the checks that found Nest still restarting.
    expect(screen.queryByText("Bad gateway")).not.toBeInTheDocument();
  });

  it("says so when Nest does not answer again", async () => {
    const api = fakeApi();
    api.health.mockRejectedValue(new TypeError("Failed to fetch"));
    const { user } = await openAccount(api);

    const reload = await confirmRestart(user);
    await wait(RESTART_POLL_MS * RESTART_POLLS);

    expect(api.health).toHaveBeenCalledTimes(RESTART_POLLS);
    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Nest did not come back. Check that the Mac is awake, then reload.",
    );
    expect(restartButton()).toHaveTextContent("Restart Nest");
    expect(restartButton()).toBeEnabled();
  });

  it("stays as it was when the Mac refuses the restart", async () => {
    const api = fakeApi();
    api.restartService.mockRejectedValue(new ApiError(500, "cannot restart"));
    const { user } = await openAccount(api);

    await user.click(screen.getByRole("button", { name: "Restart Nest" }));
    await user.click(screen.getByRole("button", { name: "Restart" }));

    expect(await screen.findByText("cannot restart")).toBeInTheDocument();
    expect(restartButton()).toHaveTextContent("Restart Nest");
    expect(restartButton()).toBeEnabled();
    expect(api.health).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
