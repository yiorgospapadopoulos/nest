import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { UsageLimits, UsagePeriod } from "../../api/types.ts";
import { STORAGE_KEY } from "../../appearance/appearance.ts";
import { RESTART_POLL_MS, RESTART_POLLS } from "../../store/actions.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { connector, usagePeriod } from "../../test/fixtures.ts";
import { memoryStorage, renderApp } from "../../test/render.tsx";
import { openSettings } from "../../test/settings.ts";

// Each section's page; the usage meters are on Agents, the connectors under Extensions.
const openAgents = (api = fakeApi()) => openSettings("Agents", { api });
const openGeneral = (api = fakeApi()) => openSettings("General", { api });
const openAppearance = (storage = memoryStorage()) =>
  openSettings("Appearance", { api: fakeApi(), storage });

async function openConnections(api = fakeApi()) {
  const rendered = await openSettings("Extensions", { api });
  await rendered.user.click(screen.getByRole("button", { name: "Connections" }));
  return rendered;
}

// Saturday 17 October 2026, 10:14 on this phone.
const TODAY = new Date(2026, 9, 17, 10, 14);
const minutesAgo = (minutes: number) => new Date(TODAY.getTime() - minutes * 60_000);
const clock = (at: Date) => at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
const september = () =>
  usagePeriod({
    start: "2026-09-01",
    end: "2026-09-30",
    current: false,
    sessions: 1,
    bars: [{ start: "2026-09-30T00:00:00+03:00", tokens: 20, sessions: 1 }],
  });
function usageCard(): HTMLElement {
  const card = screen.getByRole("group", { name: "Period" }).closest("section");
  if (card === null) throw new Error("no usage card");
  return card;
}

describe("usage", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: TODAY, toFake: ["Date"] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the limit windows with their resets and when they were reported", async () => {
    const api = fakeApi();
    const resets = new Date(TODAY);
    resets.setHours(23, 30, 0, 0);
    api.usageLimits.mockResolvedValue({
      five_hour: {
        utilization: 0.3,
        resets_at: resets.toISOString(),
        updated_at: minutesAgo(2).toISOString(),
      },
      seven_day: null,
    });
    await openAgents(api);

    const meter = await screen.findByRole("meter", { name: "5 hour used" });
    expect(meter).toHaveAttribute("aria-valuenow", "30");
    expect(screen.getByText("Resets 23:30")).toBeInTheDocument();
    expect(screen.getByText("Not reported yet")).toBeInTheDocument();
    const reported = screen.getByText(`as of ${clock(minutesAgo(2))}`);
    expect(reported).not.toHaveClass("stale");
  });

  it("says when the older window was reported and dims it after 10 minutes", async () => {
    const api = fakeApi();
    api.usageLimits.mockResolvedValue({
      five_hour: { utilization: 0.3, resets_at: null, updated_at: minutesAgo(2).toISOString() },
      seven_day: { utilization: 0.1, resets_at: null, updated_at: minutesAgo(11).toISOString() },
    });
    await openAgents(api);

    const stale = await screen.findByText(`as of ${clock(minutesAgo(11))}`);
    expect(stale).toHaveClass("stale");
    expect(stale).toHaveAttribute("title", "More than 10 minutes old");
    expect(screen.queryByText(`as of ${clock(minutesAgo(2))}`)).not.toBeInTheDocument();
  });

  it("leaves the time out until a window is reported", async () => {
    const api = fakeApi();
    api.usageLimits.mockResolvedValue({ five_hour: null, seven_day: null });
    await openAgents(api);

    expect(await screen.findAllByText("Not reported yet")).toHaveLength(2);
    expect(screen.queryByText(/^as of/)).not.toBeInTheDocument();
  });

  it("refreshes the windows on request", async () => {
    const api = fakeApi();
    let finish: (value: UsageLimits) => void = () => undefined;
    api.refreshUsage.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { user } = await openAgents(api);
    await screen.findByRole("meter", { name: "5 hour used" });

    await user.click(screen.getByRole("button", { name: "Refresh usage" }));
    expect(screen.getByRole("button", { name: "Refresh usage" })).toBeDisabled();
    act(() => {
      finish({
        five_hour: { utilization: 0.8, resets_at: null, updated_at: TODAY.toISOString() },
        seven_day: null,
      });
    });

    await waitFor(() => {
      expect(screen.getByRole("meter", { name: "5 hour used" })).toHaveAttribute(
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
    const { user } = await openAgents(api);
    const button = await screen.findByRole("button", { name: "Refresh usage" });

    await user.click(button);
    expect(await screen.findByText("Usage was refreshed moments ago")).toBeInTheDocument();
    await user.click(button);
    expect(await screen.findByText("Claude did not report the usage limits")).toBeInTheDocument();
  });

  it("toasts when account data cannot load", async () => {
    const api = fakeApi();
    api.connectors.mockRejectedValue(new ApiError(500, "registry broke"));
    await openConnections(api);

    expect(await screen.findByText("registry broke")).toBeInTheDocument();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("updates the limits live", async () => {
    const { push } = await openAgents();
    await screen.findByRole("meter", { name: "5 hour used" });

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
    expect(screen.getByRole("meter", { name: "5 hour used" })).toHaveAttribute(
      "aria-valuenow",
      "30",
    );
    expect(screen.getAllByText("Reset time unknown")).toHaveLength(2);
  });
});

describe("usage periods", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: TODAY, toFake: ["Date"] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows this month's bars and totals, with nothing after today", async () => {
    const api = fakeApi();
    await openAgents(api);

    await screen.findByText("Total · 74 chats");
    expect(api.usagePeriod).toHaveBeenCalledWith("month", "2026-10-17");
    const card = within(usageCard());
    expect(card.getByRole("button", { name: "Month" })).toHaveAttribute("aria-pressed", "true");
    expect(card.getByText("October")).toBeInTheDocument();
    expect(card.getByRole("button", { name: "Next period" })).toBeDisabled();
    const row = (label: string) => card.getByText(label).closest(".srow");
    expect(row("Chats")).toHaveTextContent("13.4M");
    expect(row("Subagents")).toHaveTextContent("1.6M");
    expect(row("Total · 74 chats")).toHaveTextContent("15M");

    const bars = card.getAllByRole("img");
    expect(bars).toHaveLength(31);
    expect(card.getByRole("img", { name: "Thu 15 Oct: 3.6M tokens, 12 chats" })).toHaveStyle({
      height: "64px",
    });
    expect(card.getByRole("img", { name: "Fri 16 Oct: 2.2M tokens, 1 chat" })).toHaveClass("on");
    expect(card.getByRole("img", { name: "Sat 17 Oct: 0 tokens, 0 chats" })).not.toHaveClass("fut");
    expect(card.getByRole("img", { name: "Sun 18 Oct: 0 tokens, 0 chats" })).toHaveClass("fut");
    expect(card.getByText("31")).toBeInTheDocument();
  });

  it("shows dashes until the period arrives", async () => {
    const api = fakeApi();
    api.usagePeriod.mockReturnValue(new Promise(() => undefined));
    await openAgents(api);

    const card = within(
      await screen.findByRole("group", { name: "Period" }).then(() => usageCard()),
    );
    expect(card.getByText("Total")).toBeInTheDocument();
    expect(card.getAllByText("-")).toHaveLength(3);
    expect(card.queryAllByRole("img")).toHaveLength(0);
    // This phone's calendar says October is the current month.
    expect(card.getByRole("button", { name: "Next period" })).toBeDisabled();
  });

  it("switches between days, weeks, months and years", async () => {
    const api = fakeApi();
    const { user } = await openAgents(api);
    await screen.findByText("Total · 74 chats");
    const card = within(usageCard());

    await user.click(card.getByRole("button", { name: "Week" }));
    expect(card.getByText("12 to 18 Oct")).toBeInTheDocument();
    expect(card.getByRole("button", { name: "Week" })).toHaveAttribute("aria-pressed", "true");
    expect(api.usagePeriod).toHaveBeenLastCalledWith("week", "2026-10-17");
    // Until the week arrives, the month's numbers are gone.
    expect(card.getByText("Total")).toBeInTheDocument();
    await user.click(card.getByRole("button", { name: "Day" }));
    expect(card.getByText("Today")).toBeInTheDocument();
    await user.click(card.getByRole("button", { name: "Year" }));
    expect(card.getByText("2026")).toBeInTheDocument();
    expect(api.usagePeriod).toHaveBeenLastCalledWith("year", "2026-10-17");
  });

  it("moves to earlier periods and back to this one", async () => {
    const api = fakeApi();
    api.usagePeriod.mockImplementation((_unit, date) =>
      Promise.resolve(date.startsWith("2026-09") ? september() : usagePeriod()),
    );
    const { user } = await openAgents(api);
    await screen.findByText("Total · 74 chats");
    const card = within(usageCard());

    await user.click(card.getByRole("button", { name: "Previous period" }));
    expect(card.getByText("September")).toBeInTheDocument();
    expect(await card.findByText("Total · 1 chat")).toBeInTheDocument();
    expect(api.usagePeriod).toHaveBeenLastCalledWith("month", "2026-09-30");
    expect(card.getByText("30")).toBeInTheDocument();
    const next = card.getByRole("button", { name: "Next period" });
    expect(next).toBeEnabled();

    await user.click(next);
    expect(api.usagePeriod).toHaveBeenLastCalledWith("month", "2026-10-01");
    expect(await card.findByText("Total · 74 chats")).toBeInTheDocument();
    expect(card.getByRole("button", { name: "Next period" })).toBeDisabled();
  });

  it("names a month of another year with its year", async () => {
    const api = fakeApi();
    api.usagePeriod.mockReturnValue(new Promise(() => undefined));
    const { user } = await openAgents(api);
    const previous = await screen.findByRole("button", { name: "Previous period" });

    for (let i = 0; i < 10; i++) await user.click(previous);
    expect(within(usageCard()).getByText("December 2025")).toBeInTheDocument();
    expect(within(usageCard()).getByRole("button", { name: "Next period" })).toBeEnabled();
  });

  it("keeps the period it moved to when an earlier one arrives late", async () => {
    const api = fakeApi();
    let slow: (value: UsagePeriod) => void = () => undefined;
    api.usagePeriod
      .mockReturnValueOnce(
        new Promise((resolve) => {
          slow = resolve;
        }),
      )
      .mockResolvedValue(september());
    const { user } = await openAgents(api);

    await user.click(await screen.findByRole("button", { name: "Previous period" }));
    const card = within(usageCard());
    expect(await card.findByText("Total · 1 chat")).toBeInTheDocument();
    act(() => {
      slow(usagePeriod());
    });
    await Promise.resolve();
    expect(card.getByText("Total · 1 chat")).toBeInTheDocument();
  });

  it("shows a touched bar's numbers in place of the axis", async () => {
    await openAgents();
    await screen.findByText("Total · 74 chats");
    const card = within(usageCard());
    const chart = card.getByRole("group", { name: "Tokens over the period" });
    vi.spyOn(chart, "getBoundingClientRect").mockReturnValue(new DOMRect(10, 0, 310, 72));

    // The 15th of 31 bars, each 10 pixels wide.
    fireEvent.pointerDown(chart, { clientX: 155 });
    expect(
      card.getByText("Thu 15 Oct: 3.6M tokens, 12 chats", { selector: ".utip" }),
    ).toBeVisible();
    expect(card.queryByText("22")).not.toBeInTheDocument();
    // Sliding across moves the pick; a move without a press does nothing.
    fireEvent.pointerMove(chart, { clientX: 165, buttons: 1 });
    expect(card.getByText(/^Fri 16 Oct/, { selector: ".utip" })).toBeInTheDocument();
    expect(card.getByRole("img", { name: /^Fri 16 Oct/ })).toHaveClass("sel");
    fireEvent.pointerMove(chart, { clientX: 15, buttons: 0 });
    expect(card.getByText(/^Fri 16 Oct/, { selector: ".utip" })).toBeInTheDocument();
    // Past either end is the first or the last bar.
    fireEvent.pointerMove(chart, { clientX: 900, buttons: 1 });
    expect(card.getByText(/^Sat 31 Oct/, { selector: ".utip" })).toBeInTheDocument();
    fireEvent.pointerMove(chart, { clientX: 0, buttons: 1 });
    expect(card.getByText(/^Thu 1 Oct/, { selector: ".utip" })).toBeInTheDocument();
    // A second tap on the same bar puts the axis back.
    fireEvent.pointerDown(chart, { clientX: 12 });
    expect(card.getByText("22")).toBeInTheDocument();
  });

  it("ignores touches on a chart with no bars or no width", async () => {
    const api = fakeApi();
    api.usagePeriod.mockReturnValue(new Promise(() => undefined));
    await openAgents(api);
    const chart = await screen.findByRole("group", { name: "Tokens over the period" });
    fireEvent.pointerDown(chart, { clientX: 5 });
    expect(within(usageCard()).getByText("22")).toBeInTheDocument();
  });

  it("ignores touches while the chart has no width", async () => {
    await openAgents();
    await screen.findByText("Total · 74 chats");
    const chart = screen.getByRole("group", { name: "Tokens over the period" });
    fireEvent.pointerDown(chart, { clientX: 5 });
    expect(within(usageCard()).getByText("22")).toBeInTheDocument();
  });
});

describe("usage breakdown", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: TODAY, toFake: ["Date"] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  async function openBreakdown(api = fakeApi()) {
    const rendered = await openAgents(api);
    await rendered.user.click(await screen.findByRole("button", { name: "Details" }));
    return rendered;
  }
  const rows = (section: string) =>
    within(screen.getByRole("region", { name: section }))
      .getAllByText((_, element) => element?.classList.contains("srow") ?? false)
      .map((row) => row.textContent);

  it("splits the period's tokens by who, kind and project", async () => {
    await openBreakdown();

    expect(screen.getByRole("heading", { name: "October tokens" })).toBeInTheDocument();
    expect(await screen.findByText("15M", { selector: ".stot" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/settings/agents/usage");
    expect(rows("By who")).toEqual(["Chats13.4M89%", "Subagents1.6M11%"]);
    expect(rows("By kind")).toEqual([
      "Cache read12.1M81%",
      "Cache write2.8M19%",
      "Output105k0.7%",
      "Input2k0.01%",
    ]);
    expect(rows("By project")).toEqual([
      "DEMO7.2M",
      "CV-page2.2M",
      "b59-live1.4M",
      "Pixies1.1M",
      "Others (2)1.5M",
    ]);
    expect(screen.getByText("12 usage checks, 5k tokens, not counted above")).toHaveClass("note");
  });

  it("goes back to Agents on the same period", async () => {
    const api = fakeApi();
    api.usagePeriod.mockImplementation((_unit, date) =>
      Promise.resolve(date.startsWith("2026-09") ? september() : usagePeriod()),
    );
    const { user } = await openAgents(api);
    await user.click(await screen.findByRole("button", { name: "Previous period" }));
    await user.click(screen.getByRole("button", { name: "Details" }));

    expect(screen.getByRole("heading", { name: "September tokens" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to Agents" }));
    expect(screen.getByRole("heading", { name: "Agents" })).toBeInTheDocument();
    expect(within(usageCard()).getByText("September")).toBeInTheDocument();
  });

  it("waits for the period, and says when no project used tokens", async () => {
    const api = fakeApi();
    let finish: (value: UsagePeriod) => void = () => undefined;
    api.usagePeriod.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    await openBreakdown(api);

    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(document.querySelector(".stot")).toBeNull();
    act(() => {
      finish(usagePeriod({ projects: [], probes: { count: 0, tokens: 0 } }));
    });
    expect(await screen.findByText("No tokens in this period")).toBeInTheDocument();
    expect(screen.queryByText(/usage check/)).not.toBeInTheDocument();
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
    const { push, user } = await openConnections(api);

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
    expect(within(ai).getByRole("link", { name: "Sign in on claude.ai" })).toHaveAttribute(
      "href",
      "https://claude.ai/settings/connectors",
    );
    expect(within(ai).getByText("Needs sign-in")).toBeInTheDocument();
    expect(screen.queryByText("spawn ENOENT")).not.toBeInTheDocument();

    await user.click(localToggle);
    const local = screen.getByRole("region", { name: /Plugins and local servers/ });
    expect(within(local).getAllByText("Set up with /mcp in Claude Code")).toHaveLength(2);
    expect(within(local).getByText(/Sign in from the Mac: run/)).toHaveTextContent(
      "Sign in from the Mac: run claude /mcp in Terminal",
    );
    expect(within(local).getByText("spawn ENOENT")).toBeInTheDocument();
    expect(within(local).getByText("disabled")).toBeInTheDocument();
    // Connecting is a loading state: fireflies in the pill (B80).
    expect(within(local).getByText("Connecting").previousElementSibling).toHaveClass("ff");

    await user.click(aiToggle);
    expect(aiToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Gmail")).not.toBeInTheDocument();

    push({ id: 3, type: "connectors.updated", payload: { connectors: [] } });
    expect(screen.getByText(/None reported yet/)).toBeInTheDocument();
  });

  it("copies the command that signs in to a server on the Mac", async () => {
    const api = fakeApi();
    api.connectors.mockResolvedValue([
      connector({
        name: "linear",
        display_name: "linear",
        group: "local",
        status: "needs-auth",
        manage_hint: "claude_code",
      }),
    ]);
    const { user } = await openConnections(api);
    await user.click(await screen.findByRole("button", { name: /Plugins and local servers/ }));

    await user.click(screen.getByRole("button", { name: "Copy" }));

    expect(await navigator.clipboard.readText()).toBe("claude /mcp");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("keeps offering the copy when the clipboard refuses", async () => {
    const api = fakeApi();
    api.connectors.mockResolvedValue([
      connector({
        name: "linear",
        group: "local",
        status: "needs-auth",
        manage_hint: "claude_code",
      }),
    ]);
    const { user } = await openConnections(api);
    await user.click(await screen.findByRole("button", { name: /Plugins and local servers/ }));
    const refuse = vi
      .spyOn(navigator.clipboard, "writeText")
      .mockRejectedValue(new Error("not allowed"));

    await user.click(screen.getByRole("button", { name: "Copy" }));

    await waitFor(() => {
      expect(refuse).toHaveBeenCalledWith("claude /mcp");
    });
    expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
    refuse.mockRestore();
  });

  it("shows no attention hint when every connector in a group is fine", async () => {
    const api = fakeApi();
    api.connectors.mockResolvedValue([connector()]);
    await openConnections(api);

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
    const { user } = await openAppearance(storage);
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

  it("switches the glass theme at once and previews every theme", async () => {
    const storage = memoryStorage();
    const { user } = await openAppearance(storage);
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

  /** The General page once it showed the version, so later health checks are the restart's. */
  async function openNest(api: ReturnType<typeof fakeApi>) {
    const rendered = await openGeneral(api);
    expect(await screen.findByText("0.1.0")).toBeInTheDocument();
    api.health.mockClear();
    return rendered;
  }

  /** Confirms the restart with fake timers, so the waits between checks are in the test's hands. */
  async function confirmRestart(user: Awaited<ReturnType<typeof openGeneral>>["user"]) {
    await user.click(restartButton());
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

  it("shows the version, sits at the very bottom and asks first", async () => {
    const api = fakeApi();
    const { user } = await openNest(api);

    const sections = screen.getAllByRole("region");
    expect(sections.at(-1)).toHaveAccessibleName("Nest");
    await user.click(restartButton());
    const dialog = screen.getByRole("alertdialog", { name: "Restart Nest?" });
    expect(dialog).toHaveTextContent(/Running turns are interrupted/);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(api.restartService).not.toHaveBeenCalled();
  });

  it("restarts Nest and reloads the page once it answers again", async () => {
    const api = fakeApi();
    const { user } = await openNest(api);
    api.health
      .mockRejectedValueOnce(new ApiError(502, "Bad gateway"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));

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
    const { user } = await openNest(api);
    api.health.mockRejectedValue(new TypeError("Failed to fetch"));

    const reload = await confirmRestart(user);
    await wait(RESTART_POLL_MS * RESTART_POLLS);

    expect(api.health).toHaveBeenCalledTimes(RESTART_POLLS);
    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Nest did not come back. Check that the Mac is awake, then reload.",
    );
    expect(restartButton()).toHaveTextContent("Restart");
    expect(restartButton()).toBeEnabled();
  });

  it("stays as it was when the Mac refuses the restart", async () => {
    const api = fakeApi();
    api.restartService.mockRejectedValue(new ApiError(500, "cannot restart"));
    const { user } = await openNest(api);

    await user.click(restartButton());
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Restart" }),
    );

    expect(await screen.findByText("cannot restart")).toBeInTheDocument();
    expect(restartButton()).toHaveTextContent("Restart");
    expect(restartButton()).toBeEnabled();
    expect(api.health).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
