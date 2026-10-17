import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { detail, habit, habitRun, pixie, session } from "../../test/fixtures.ts";
import { openPixie } from "../../test/pixies.ts";

const details = (api = fakeApi()) => openPixie(api, pixie(), "Details");

const sheet = (name: string) => screen.getByRole("dialog", { name });

async function openHabits(api = fakeApi()) {
  const rendered = await details(api);
  await rendered.user.click(screen.getByRole("button", { name: /^Habits/ }));
  return rendered;
}

describe("Pixie habits page (B42)", () => {
  it("lists each habit with its schedule, triggers, last run and next run", async () => {
    const api = fakeApi();
    const now = new Date();
    api.habits.mockResolvedValue([
      habit({
        id: "h1",
        name: "Morning check",
        last_run: habitRun({ outcome: "quiet", started_at: now.toISOString() }),
        next_due_at: now.toISOString(),
      }),
      habit({
        id: "h2",
        name: "Watch CI",
        schedule: null,
        triggers: ["ci_failed", "stuck"],
        enabled: false,
      }),
      habit({
        id: "h3",
        name: "Late one",
        last_run: habitRun({
          outcome: "skipped",
          reason: "late",
          started_at: null,
          due_at: "2026-10-01T07:00:00Z",
        }),
      }),
      habit({
        id: "h4",
        name: "Odd one",
        last_run: habitRun({ outcome: "failed", started_at: null, due_at: null }),
      }),
    ]);
    const { user } = await details(api);
    // The row counts them once they are known.
    await user.click(await screen.findByRole("button", { name: /^Habits.*4 habits/ }));

    const page = sheet("Habits");
    const rows = await within(page).findAllByRole("listitem");
    expect(api.habits).toHaveBeenCalledWith("p1");
    expect(rows).toHaveLength(4);
    const first = defined(rows[0]);
    expect(first).toHaveTextContent("Morning check");
    expect(first).toHaveTextContent("Weekdays at 09:00");
    expect(first).toHaveTextContent(/Nothing to report \d\d:\d\d/);
    expect(first).toHaveTextContent(/Next \d\d:\d\d/);
    expect(within(first).getByRole("switch", { name: "Morning check on" })).toBeChecked();
    const second = defined(rows[1]);
    expect(second).toHaveTextContent("No schedule");
    expect(second).toHaveTextContent("When pull request checks fail or a chat looks stuck");
    expect(second).toHaveTextContent("Never run");
    expect(within(second).getByRole("switch", { name: "Watch CI on" })).not.toBeChecked();
    // Skipped runs never started: their due time shows.
    expect(defined(rows[2])).toHaveTextContent(/Skipped \(late\) 1 Oct \d\d:\d\d/);
    expect(within(defined(rows[3])).getByText("Failed").parentElement).toHaveTextContent(
      /^Failed$/,
    );
  });

  it("says when there are none or they cannot load", async () => {
    const api = fakeApi();
    api.habits.mockRejectedValue(new Error("Mac asleep"));
    const { user } = await openHabits(api);
    expect(
      await within(sheet("Habits")).findByText("The habits could not be loaded."),
    ).toBeInTheDocument();
    await user.click(within(sheet("Habits")).getByRole("button", { name: "Done" }));

    api.habits.mockResolvedValue([]);
    await user.click(screen.getByRole("button", { name: /^Habits/ }));
    expect(await within(sheet("Habits")).findByText(/No habits yet/)).toBeInTheDocument();
  });

  it("creates a habit from the editor, with a schedule and a trigger", async () => {
    const api = fakeApi();
    const { user } = await openHabits(api);
    const add = await within(sheet("Habits")).findByRole("button", { name: "New habit" });
    // At the full right of its row, with no heading repeating the sheet's title (B85).
    expect(add.parentElement).toHaveClass("pxhrow");
    expect(add.parentElement?.children).toHaveLength(1);
    expect(within(sheet("Habits")).getAllByRole("heading", { name: "Habits" })).toHaveLength(1);
    expect(add).toHaveTextContent("New");
    await user.click(add);

    const editor = sheet("New habit");
    const save = within(editor).getByRole("button", { name: "Save" });
    // Nothing to save without a name, a prompt, and a schedule or a trigger; an empty name
    // only leaves Save off, with no message.
    expect(save).toBeDisabled();
    expect(within(editor).queryByText(/name the habit/i)).not.toBeInTheDocument();
    await user.type(within(editor).getByLabelText("Name"), "Hourly sweep");
    await user.type(within(editor).getByLabelText("What to check"), "Look for stuck chats");
    expect(save).toBeDisabled();
    expect(within(editor).getByText("Choose a schedule or a trigger.")).toBeInTheDocument();

    await user.selectOptions(within(editor).getByLabelText("Schedule"), "hourly");
    const minute = within(editor).getByLabelText("Minute");
    await user.clear(minute);
    await user.type(minute, "15");
    // Each trigger reads as its words, also to VoiceOver.
    for (const name of [
      "When a chat looks stuck",
      "When a chat fails",
      "When work is ready for review",
      "When pull request checks fail",
    ]) {
      const box = within(editor).getByRole("checkbox", { name });
      expect(box).not.toBeChecked();
      // Named explicitly: the wrapping label alone left it "on" in Safari and Chrome.
      expect(document.getElementById(box.getAttribute("aria-labelledby") ?? "")).toHaveTextContent(
        name,
      );
    }
    await user.click(within(editor).getByRole("checkbox", { name: "When a chat fails" }));
    // A pixie works in every project, so no note limits its triggers (B85).
    expect(within(editor).queryByText("Choose a schedule or a trigger.")).not.toBeInTheDocument();
    expect(within(editor).queryByText(/projects/)).not.toBeInTheDocument();
    const limit = within(editor).getByLabelText("Longest run, in minutes");
    await user.clear(limit);
    await user.type(limit, "30");
    await user.click(save);

    expect(api.createHabit).toHaveBeenCalledWith("p1", {
      name: "Hourly sweep",
      prompt: "Look for stuck chats",
      schedule: { kind: "hourly", minute: 15 },
      triggers: ["failed"],
      max_minutes: 30,
      enabled: true,
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "New habit" })).not.toBeInTheDocument();
    });
    expect(within(sheet("Habits")).getByText("Hourly sweep")).toBeInTheDocument();
  });

  it("offers the time fields each schedule needs", async () => {
    const api = fakeApi();
    const { user } = await openHabits(api);
    await user.click(await within(sheet("Habits")).findByRole("button", { name: "New habit" }));
    const editor = sheet("New habit");
    const schedule = within(editor).getByLabelText("Schedule");
    await user.type(within(editor).getByLabelText("Name"), "Weekly");
    await user.type(within(editor).getByLabelText("What to check"), "Sum up the week");

    await user.selectOptions(schedule, "weekly");
    await user.selectOptions(within(editor).getByLabelText("Day"), "4");
    const time = within(editor).getByLabelText("Time");
    expect(time).toHaveValue("09:00");
    // An emptied time keeps the last one.
    fireEvent.change(time, { target: { value: "18:30" } });
    fireEvent.change(time, { target: { value: "" } });
    expect(time).toHaveValue("18:30");
    await user.click(within(editor).getByRole("button", { name: "Save" }));
    expect(api.createHabit).toHaveBeenLastCalledWith(
      "p1",
      expect.objectContaining({ schedule: { kind: "weekly", weekday: 4, time: "18:30" } }),
    );

    await user.click(await within(sheet("Habits")).findByRole("button", { name: "New habit" }));
    const second = sheet("New habit");
    await user.type(within(second).getByLabelText("Name"), "Daily");
    await user.type(within(second).getByLabelText("What to check"), "Check");
    await user.selectOptions(within(second).getByLabelText("Schedule"), "daily");
    expect(within(second).queryByLabelText("Day")).not.toBeInTheDocument();
    await user.selectOptions(within(second).getByLabelText("Schedule"), "weekdays");
    await user.selectOptions(within(second).getByLabelText("Schedule"), "none");
    expect(within(second).queryByLabelText("Time")).not.toBeInTheDocument();
    await user.click(within(second).getByLabelText("When work is ready for review"));
    await user.click(within(second).getByLabelText("When a chat looks stuck"));
    await user.click(within(second).getByLabelText("When work is ready for review"));
    await user.click(within(second).getByRole("button", { name: "Save" }));
    expect(api.createHabit).toHaveBeenLastCalledWith(
      "p1",
      expect.objectContaining({ schedule: null, triggers: ["stuck"] }),
    );
  });

  it("keeps the editor open when the Mac refuses, and cancels without saving", async () => {
    const api = fakeApi();
    api.createHabit.mockRejectedValueOnce(new Error("Name taken"));
    const { user } = await openHabits(api);
    await user.click(await within(sheet("Habits")).findByRole("button", { name: "New habit" }));
    const editor = sheet("New habit");
    await user.type(within(editor).getByLabelText("Name"), "Check");
    await user.type(within(editor).getByLabelText("What to check"), "Look");
    await user.click(within(editor).getByLabelText("When a chat fails"));
    await user.click(within(editor).getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Name taken")).toBeInTheDocument();
    expect(sheet("New habit")).toBeInTheDocument();
    await user.click(within(editor).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog", { name: "New habit" })).not.toBeInTheDocument();
  });

  it("edits a habit with its current values", async () => {
    const api = fakeApi();
    api.habits.mockResolvedValue([
      habit({ triggers: ["stuck"], schedule: { kind: "weekly", weekday: 2, time: "07:45" } }),
    ]);
    const { user } = await openHabits(api);
    await user.click(
      await within(sheet("Habits")).findByRole("button", { name: /^Morning check/ }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Edit" }));

    const editor = sheet("Edit habit");
    expect(within(editor).getByLabelText("Name")).toHaveValue("Morning check");
    expect(within(editor).getByLabelText("Day")).toHaveValue("2");
    expect(within(editor).getByLabelText("Time")).toHaveValue("07:45");
    expect(within(editor).getByLabelText("When a chat looks stuck")).toBeChecked();
    await user.clear(within(editor).getByLabelText("Name"));
    await user.type(within(editor).getByLabelText("Name"), "Midweek check");
    await user.click(within(editor).getByRole("button", { name: "Save" }));

    expect(api.updateHabit).toHaveBeenCalledWith("p1", "h1", {
      name: "Midweek check",
      prompt: "Look at yesterday's chats and report anything stuck.",
      schedule: { kind: "weekly", weekday: 2, time: "07:45" },
      triggers: ["stuck"],
      max_minutes: 20,
    });
    expect(await within(sheet("Habits")).findByText("Midweek check")).toBeInTheDocument();
  });

  it("edits an hourly habit's minute", async () => {
    const api = fakeApi();
    api.habits.mockResolvedValue([habit({ schedule: { kind: "hourly", minute: 45 } })]);
    const { user } = await openHabits(api);
    await user.click(
      await within(sheet("Habits")).findByRole("button", { name: /^Morning check/ }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Edit" }));

    const minute = within(sheet("Edit habit")).getByLabelText("Minute");
    expect(minute).toHaveValue(45);
    await user.clear(minute);
    await user.type(minute, "75");
    expect(within(sheet("Edit habit")).getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("pauses and resumes from the switch or the menu, and runs now", async () => {
    const api = fakeApi();
    api.habits.mockResolvedValue([habit({ schedule: { kind: "hourly", minute: 0 } })]);
    const { user } = await details(api);
    await user.click(await screen.findByRole("button", { name: /^Habits.*1 habit$/ }));
    await user.click(
      await within(sheet("Habits")).findByRole("switch", { name: "Morning check on" }),
    );
    expect(api.updateHabit).toHaveBeenLastCalledWith("p1", "h1", { enabled: false });
    await waitFor(() => {
      expect(within(sheet("Habits")).getByRole("switch")).not.toBeChecked();
    });
    expect(within(sheet("Habits")).getByText("Paused")).toBeInTheDocument();

    await user.click(within(sheet("Habits")).getByRole("button", { name: /^Morning check/ }));
    await user.click(screen.getByRole("menuitem", { name: "Resume" }));
    expect(api.updateHabit).toHaveBeenLastCalledWith("p1", "h1", { enabled: true });
    await waitFor(() => {
      expect(within(sheet("Habits")).getByRole("switch")).toBeChecked();
    });
    await user.click(within(sheet("Habits")).getByRole("button", { name: /^Morning check/ }));
    await user.click(screen.getByRole("menuitem", { name: "Pause" }));
    expect(api.updateHabit).toHaveBeenLastCalledWith("p1", "h1", { enabled: false });
    await waitFor(() => {
      expect(within(sheet("Habits")).getByRole("switch")).not.toBeChecked();
    });

    await user.click(within(sheet("Habits")).getByRole("button", { name: /^Morning check/ }));
    await user.click(screen.getByRole("menuitem", { name: "Run now" }));
    expect(api.runHabit).toHaveBeenCalledWith("p1", "h1");
    expect(await screen.findByText("Run queued")).toBeInTheDocument();
    expect(within(sheet("Habits")).getByText("Queued")).toBeInTheDocument();
  });

  it("deletes a habit once confirmed", async () => {
    const api = fakeApi();
    api.habits.mockResolvedValue([habit()]);
    const { user } = await openHabits(api);
    await user.click(
      await within(sheet("Habits")).findByRole("button", { name: /^Morning check/ }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Delete…" }));
    const confirm = screen.getByRole("alertdialog", { name: "Delete Morning check?" });
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));

    expect(api.deleteHabit).toHaveBeenCalledWith("p1", "h1");
    expect(await within(sheet("Habits")).findByText(/No habits yet/)).toBeInTheDocument();
  });

  it("shows the history and opens a run's transcript read only", async () => {
    const api = fakeApi();
    const run = session({
      id: "hs1",
      title: "Morning check",
      repo: "pixie:p1",
      pixie_id: "p1",
      habit_run_id: "r1",
    });
    api.habits.mockResolvedValue([habit()]);
    api.habitRuns.mockResolvedValue([
      habitRun({
        id: "r2",
        outcome: "running",
        ended_at: null,
        report_title: null,
        session_id: null,
      }),
      habitRun(),
      habitRun({ id: "r0", outcome: "skipped", reason: "late", started_at: null, ended_at: null }),
    ]);
    api.session.mockResolvedValue(detail(run));
    const { user, push } = await openHabits(api);
    await user.click(
      await within(sheet("Habits")).findByRole("button", { name: /^Morning check/ }),
    );
    await user.click(screen.getByRole("menuitem", { name: "History" }));

    const history = sheet("Morning check history");
    const rows = await within(history).findAllByRole("listitem");
    expect(api.habitRuns).toHaveBeenCalledWith("p1", "h1");
    expect(defined(rows[0])).toHaveTextContent("Running");
    expect(defined(rows[1])).toHaveTextContent("Reported");
    expect(defined(rows[1])).toHaveTextContent("2m 30s");
    expect(defined(rows[1])).toHaveTextContent("Two chats are stuck");
    expect(defined(rows[2])).toHaveTextContent("Skipped (late)");
    expect(within(defined(rows[0])).queryByRole("button")).not.toBeInTheDocument();

    await user.click(within(defined(rows[1])).getByRole("button", { name: "Open transcript" }));
    expect(await screen.findByRole("region", { name: "Morning check" })).toBeInTheDocument();
    expect(api.session).toHaveBeenCalledWith("hs1");
    // A run's chat is read only, and not the pixie's own page.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Details" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to Tester" })).toBeInTheDocument();
    push({ type: "pixie.deleted", payload: { pixie_id: "p1" } });
    expect(screen.getByRole("button", { name: "Back to Pixie" })).toBeInTheDocument();
  });

  it("says when the history is empty or cannot load", async () => {
    const api = fakeApi();
    api.habits.mockResolvedValue([habit()]);
    api.habitRuns.mockRejectedValueOnce(new Error("Mac asleep"));
    const { user } = await openHabits(api);
    const openHistory = async () => {
      await user.click(
        await within(sheet("Habits")).findByRole("button", { name: /^Morning check/ }),
      );
      await user.click(screen.getByRole("menuitem", { name: "History" }));
    };
    await openHistory();
    expect(
      await within(sheet("Morning check history")).findByText("The history could not be loaded."),
    ).toBeInTheDocument();
    await user.click(within(sheet("Morning check history")).getByRole("button", { name: "Done" }));
    await openHistory();
    expect(
      await within(sheet("Morning check history")).findByText("No runs yet"),
    ).toBeInTheDocument();
  });

  it("follows habits changed elsewhere", async () => {
    const api = fakeApi();
    api.habits.mockResolvedValue([habit()]);
    const { push } = await openHabits(api);
    await within(sheet("Habits")).findByText("Morning check");

    push({
      type: "habit.updated",
      payload: { habit: habit({ id: "h2", name: "Evening check" }) } as never,
    });
    expect(within(sheet("Habits")).getByText("Evening check")).toBeInTheDocument();
  });
});
