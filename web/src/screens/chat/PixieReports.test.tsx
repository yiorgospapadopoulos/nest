import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { NestEvent, JsonObject } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { detail, event, habit, pixie, report, session, NOW } from "../../test/fixtures.ts";
import { openPixie, showPixies } from "../../test/pixies.ts";
import { renderApp } from "../../test/render.tsx";

const tester = pixie({ id: "p1", name: "Tester", mascot: "moth", chat_session_id: "pc" });
const pixieChat = session({ id: "pc", title: "Tester", repo: "pixie:p1", pixie_id: "p1" });

/** The app with the pixie and the events of its chat. */
function withChat(events: NestEvent[] = []): FakeApi {
  const api = fakeApi();
  api.pixies.mockResolvedValue([tester]);
  api.session.mockResolvedValue(detail(pixieChat));
  api.sessionEvents.mockResolvedValue(events);
  return api;
}

const card = (id: number, payload: JsonObject) =>
  event({ id, session_id: "pc", type: "pixie.card", payload });

const said = (id: number, text: string, origin?: string) =>
  event({
    id,
    session_id: "pc",
    type: "session.user_message",
    payload: origin === undefined ? { text } : { text, origin },
  });

describe("report cards in a pixie's chat (B42)", () => {
  it("shows the report with its severity, link and habit", async () => {
    const api = withChat([
      card(1, { kind: "report", report_id: "a" }),
      card(2, { kind: "report", report_id: "b" }),
      card(3, { kind: "report", report_id: "c" }),
      card(4, { kind: "report", report_id: "gone" }),
      said(5, "Report from habit Morning check: CI is failing on main", "report"),
    ]);
    api.pixieReports.mockResolvedValue([
      report({
        id: "a",
        link: "https://github.com/me/cv-page/actions/runs/1",
        habit_id: "h1",
        read_at: NOW,
      }),
      report({ id: "b", severity: "info", title: "All quiet", habit_id: "h9", read_at: NOW }),
      report({
        id: "c",
        severity: "warn",
        title: "Disk almost full",
        link: "javascript:alert(1)",
        read_at: NOW,
      }),
    ]);
    api.habits.mockResolvedValue([habit()]);
    await openPixie(api, tester);

    const action = await screen.findByRole("group", { name: "Report: CI is failing on main" });
    expect(action).toHaveClass("sev-action");
    expect(action).toHaveTextContent("Needs action");
    expect(action).toHaveTextContent("Two runs failed on the lint step.");
    expect(await within(action).findByText("From habit Morning check")).toBeInTheDocument();
    expect(within(action).getByRole("link", { name: "Open link" })).toHaveAttribute(
      "href",
      "https://github.com/me/cv-page/actions/runs/1",
    );
    const info = screen.getByRole("group", { name: "Report: All quiet" });
    expect(info).toHaveClass("sev-info");
    expect(info).toHaveTextContent("From a habit");
    expect(within(info).queryByRole("link")).not.toBeInTheDocument();
    const warn = screen.getByRole("group", { name: "Report: Disk almost full" });
    expect(warn).toHaveTextContent("Warning");
    expect(warn).not.toHaveTextContent("From");
    // Only web addresses become links.
    expect(within(warn).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Report" })).toHaveTextContent(
      "This report is no longer kept.",
    );

    const row = screen.getByText("Habit report").parentElement;
    expect(row).toHaveClass("m-sys");
    expect(row).toHaveTextContent("Report from habit Morning check: CI is failing on main");
  });

  it("shows a report that arrives live", async () => {
    const api = withChat();
    const { push } = await openPixie(api, tester);
    await waitFor(() => {
      expect(api.sessionEvents).toHaveBeenCalledWith("pc");
    });

    push({ type: "pixie.report", payload: { report: report({ title: "Fresh news" }) } as never });
    push(card(1, { kind: "report", report_id: "rep1" }));
    expect(await screen.findByRole("group", { name: "Report: Fresh news" })).toBeInTheDocument();
  });
});

describe("cards outside a pixie's chat (B42)", () => {
  it("are left out", async () => {
    const api = fakeApi();
    const chat = session({ id: "s1", title: "Check the form" });
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
    api.session.mockResolvedValue(detail(chat));
    api.sessionEvents.mockResolvedValue([
      event({ id: 1, type: "pixie.card", payload: { kind: "choices", options: ["Yes"] } }),
      event({ id: 2, type: "session.user_message", payload: { text: "Hello" } }),
    ]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: /^Check the form,/ }));

    expect(await screen.findByText("Hello")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Choices" })).not.toBeInTheDocument();
  });
});

describe("choices cards (B42)", () => {
  it("send the chosen option as the user's reply, once", async () => {
    const api = withChat([card(1, { kind: "choices", options: ["Fix it", "Leave it"] })]);
    const { user } = await openPixie(api, tester);

    const choices = await screen.findByRole("group", { name: "Choices" });
    await user.click(within(choices).getByRole("button", { name: "Fix it" }));
    expect(api.sendToPixie).toHaveBeenCalledWith("p1", "Fix it");
    for (const button of within(choices).getAllByRole("button")) expect(button).toBeDisabled();
  });

  it("can be chosen again when sending failed", async () => {
    const api = withChat([card(1, { kind: "choices", options: ["Fix it"] })]);
    api.sendToPixie.mockRejectedValueOnce(new Error("Mac asleep"));
    const { user } = await openPixie(api, tester);

    const choices = await screen.findByRole("group", { name: "Choices" });
    await user.click(within(choices).getByRole("button", { name: "Fix it" }));
    expect(await screen.findByText("Mac asleep")).toBeInTheDocument();
    expect(within(choices).getByRole("button", { name: "Fix it" })).toBeEnabled();
  });

  it("are disabled once the user wrote after them", async () => {
    const api = withChat([card(1, { kind: "choices", options: ["Fix it"] }), said(2, "Later")]);
    await openPixie(api, tester);

    const choices = await screen.findByRole("group", { name: "Choices" });
    expect(within(choices).getByRole("button", { name: "Fix it" })).toBeDisabled();
  });
});

describe("habit suggestion cards (B42)", () => {
  const suggested = {
    name: "Watch CI",
    prompt: "Say when checks fail on main",
    schedule: { kind: "hourly", minute: 15 },
    triggers: ["ci_failed"],
  };

  it("start the suggested habit, enabled", async () => {
    const api = withChat([card(1, { kind: "habit_suggestion", habit: suggested })]);
    // Started shows even while the pixie's habits are not known.
    api.habits.mockRejectedValue(new Error("Mac asleep"));
    const { user } = await openPixie(api, tester);

    const shown = await screen.findByRole("group", { name: "Suggested habit: Watch CI" });
    expect(shown).toHaveTextContent("Every hour at :15");
    expect(shown).toHaveTextContent("When pull request checks fail");
    expect(within(shown).getByText("Say when checks fail on main")).not.toBeVisible();
    await user.click(within(shown).getByText("Prompt"));
    expect(within(shown).getByText("Say when checks fail on main")).toBeVisible();

    await user.click(within(shown).getByRole("button", { name: "Start" }));
    expect(api.createHabit).toHaveBeenCalledWith("p1", {
      name: "Watch CI",
      prompt: "Say when checks fail on main",
      schedule: { kind: "hourly", minute: 15 },
      triggers: ["ci_failed"],
      enabled: true,
    });
    expect(await within(shown).findByText("Started")).toBeInTheDocument();
    expect(within(shown).queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
  });

  it("say Started when a habit of that name exists, and offer Start again after a refusal", async () => {
    const api = withChat([
      card(1, { kind: "habit_suggestion", habit: { ...suggested, name: "Morning check" } }),
      card(2, { kind: "habit_suggestion", habit: { ...suggested, schedule: null, triggers: [] } }),
    ]);
    api.habits.mockResolvedValue([habit()]);
    api.createHabit.mockRejectedValueOnce(new Error("Needs a schedule or a trigger"));
    const { user } = await openPixie(api, tester);

    const existing = await screen.findByRole("group", { name: "Suggested habit: Morning check" });
    expect(await within(existing).findByText("Started")).toBeInTheDocument();
    const other = screen.getByRole("group", { name: "Suggested habit: Watch CI" });
    expect(other).toHaveTextContent("No schedule");
    await user.click(within(other).getByRole("button", { name: "Start" }));
    expect(await screen.findByText("Needs a schedule or a trigger")).toBeInTheDocument();
    expect(within(other).getByRole("button", { name: "Start" })).toBeEnabled();
  });
});

describe("reports in the inbox and the pixie list (B42)", () => {
  function withReports(): FakeApi {
    const api = fakeApi();
    api.pixies.mockResolvedValue([
      tester,
      pixie({ id: "p2", name: "Quiet", slug: "quiet" }),
      pixie({ id: "p3", name: "Other", slug: "other" }),
    ]);
    api.session.mockResolvedValue(detail(pixieChat));
    api.pixieReports.mockResolvedValue([
      report({ id: "a", title: "CI is failing on main" }),
      report({ id: "b", severity: "warn", title: "Disk almost full" }),
      report({ id: "c", severity: "info", title: "All quiet" }),
      report({ id: "d", title: "Old one", read_at: NOW }),
      report({ id: "e", pixie_id: "p2", title: "Quiet needs you" }),
    ]);
    return api;
  }

  it("lists unread warn and action reports; Dismiss marks one read", async () => {
    const api = withReports();
    const { user } = await renderApp({ api });

    expect(api.pixieReports).toHaveBeenCalledWith(false);
    const action = await screen.findByRole("article", { name: "Report: CI is failing on main" });
    // A closed row: its pixie, then the severity and title; Dismiss once opened (B102).
    await user.click(within(action).getByRole("button", { name: "Show details" }));
    expect(action).toHaveTextContent("Needs action · CI is failing on main");
    expect(action).toHaveTextContent("Tester");
    expect(screen.getByRole("article", { name: "Report: Disk almost full" })).toBeInTheDocument();
    expect(screen.queryByText("All quiet")).not.toBeInTheDocument();
    expect(screen.queryByText("Old one")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Needs you/ })).toHaveTextContent("3");

    await user.click(within(action).getByRole("button", { name: "Dismiss" }));
    expect(api.readReport).toHaveBeenCalledWith("a");
    await waitFor(() => {
      expect(
        screen.queryByRole("article", { name: "Report: CI is failing on main" }),
      ).not.toBeInTheDocument();
    });
  });

  it("keeps a report whose dismissal failed", async () => {
    const api = withReports();
    api.readReport.mockRejectedValueOnce(new Error("Mac asleep"));
    const { user } = await renderApp({ api });

    const action = await screen.findByRole("article", { name: "Report: CI is failing on main" });
    await user.click(within(action).getByRole("button", { name: "Show details" }));
    await user.click(within(action).getByRole("button", { name: "Dismiss" }));
    expect(await screen.findByText("Mac asleep")).toBeInTheDocument();
    expect(action).toBeInTheDocument();
  });

  it("opens the pixie from a report, which marks its reports read", async () => {
    const api = withReports();
    const { user, push } = await renderApp({ api });

    const action = await screen.findByRole("article", { name: "Report: CI is failing on main" });
    await user.click(within(action).getByRole("button", { name: "Show details" }));
    await user.click(within(action).getByRole("button", { name: "Open" }));
    expect(await screen.findByRole("tab", { name: "Chat" })).toBeInTheDocument();
    await waitFor(() => {
      expect(api.readPixieReports).toHaveBeenCalledWith("p1");
    });
    expect(api.readPixieReports).toHaveBeenCalledTimes(1);

    // A report arriving while the pixie is open is read at once.
    push({ type: "pixie.report", payload: { report: report({ id: "e" }) } as never });
    await waitFor(() => {
      expect(api.readPixieReports).toHaveBeenCalledTimes(2);
    });

    await user.click(screen.getByRole("button", { name: "Back to Pixies" }));
    await user.click(screen.getByRole("tab", { name: "Needs you" }));
    expect(screen.queryByRole("article", { name: /^Report/ })).not.toBeInTheDocument();
  });

  it("counts unread reports in the Pixies view and action reports on each pixie's row", async () => {
    const api = withReports();
    const { user } = await renderApp({ api });
    await showPixies(user);

    // The unread warn and action reports, listed above the pixies (B102).
    const reports = await screen.findByRole("region", { name: "Reports" });
    expect(within(reports).getByRole("heading")).toHaveTextContent("Reports3");
    const row = screen.getByRole("button", { name: /^Tester,/ });
    expect(row).toHaveAccessibleName("Tester, @tester, 1 report needs action");
    expect(screen.getByRole("button", { name: /^Quiet,/ })).toHaveAccessibleName(
      "Quiet, @quiet, 1 report needs action",
    );
    expect(screen.getByRole("button", { name: /^Other,/ })).toHaveAccessibleName("Other, @other");
  });

  it("marks reads for a pixie the Mac counts unread reports of, though none are listed", async () => {
    const api = fakeApi();
    await openPixie(api, pixie({ unread_action_reports: 2 }));
    await waitFor(() => {
      expect(api.readPixieReports).toHaveBeenCalledWith("p1");
    });
  });

  it("names a report's pixie that is not known", async () => {
    const api = fakeApi();
    api.pixieReports.mockResolvedValue([report({ pixie_id: "gone", body: "" })]);
    const { user } = await renderApp({ api });

    const card = await screen.findByRole("article", { name: "Report: CI is failing on main" });
    await user.click(within(card).getByRole("button", { name: "Show details" }));
    expect(card).toHaveTextContent("A pixie");
    await user.click(within(card).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => {
      expect(card).not.toBeInTheDocument();
    });
  });

  it("does not mark anything read for a pixie with no unread reports", async () => {
    const api = fakeApi();
    await openPixie(api, tester);
    await waitFor(() => {
      expect(api.habits).toHaveBeenCalledWith("p1");
    });
    expect(api.readPixieReports).not.toHaveBeenCalled();
  });

  it("keeps the reports unread when marking them read failed", async () => {
    const api = withReports();
    api.readPixieReports.mockRejectedValue(new Error("Mac asleep"));
    const { user } = await renderApp({ api });
    await showPixies(user);
    await user.click(await screen.findByRole("button", { name: /^Tester,/ }));
    await waitFor(() => {
      expect(api.readPixieReports).toHaveBeenCalled();
    });
    await user.click(screen.getByRole("button", { name: "Back to Pixies" }));
    expect(screen.getByRole("button", { name: /^Tester,/ })).toHaveAccessibleName(
      "Tester, @tester, 1 report needs action",
    );
    expect(screen.getByRole("article", { name: "Report: CI is failing on main" })).toBeVisible();
  });
});
