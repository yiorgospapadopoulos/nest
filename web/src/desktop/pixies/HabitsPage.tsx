// A pixie's habits in its details panel (B42, PixieHabitsPage.swift): the list, New habit
// and Edit, and each habit's history with its runs' transcripts.
import { useEffect, useState } from "react";
import type { Habit, HabitRun, Pixie } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { CheckBox } from "../settings/rows.tsx";
import { Confirm } from "../sheets/Alert.tsx";
import { useShell } from "../shell/context.ts";
import { Button, Toggle } from "../ui/controls.tsx";
import { separator } from "../ui/menuItems.ts";
import { RowActionsMenu, StatusDot } from "./bits.tsx";
import { GitHubRows } from "./GitHubRows.tsx";
import { TimeField } from "./TimeField.tsx";
import { useNow } from "./useNow.ts";
import { PxGlyph } from "./glyphs.tsx";
import {
  canSave,
  createBody,
  draftOf,
  EMPTY_HISTORY,
  EMPTY_LIST,
  habitSummary,
  lastRunText,
  MAX_MINUTES,
  newDraft,
  nextRunText,
  OUTCOMES,
  problemOf,
  REPEATS,
  runDuration,
  startedText,
  TRIGGERS,
  updateBody,
  WEEKDAY_NAMES,
  type HabitDraft,
} from "./habitText.ts";
import type { PixiePage } from "./panel.ts";
import {
  DetailHeading,
  DetailLine,
  DetailNote,
  Page,
  PanelPageHeader,
  PickerRow,
  StepperRow,
} from "./parts.tsx";

type Open = (page: PixiePage) => void;

/** Loads the pixie's habits; false once they could not be read. */
function useHabits(pixie: string): boolean {
  const { actions } = useStore();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let current = true;
    void actions.loadHabits(pixie).then((habits) => {
      if (current) setFailed(habits === null);
    });
    return () => {
      current = false;
    };
  }, [actions, pixie]);
  return !failed;
}

/**
 * The pixie's habits: name, schedule and triggers, the on switch, the last outcome and
 * the next run; Run now, History and a menu with Edit, Pause or Resume and Delete.
 */
export function HabitsPage({ pixie, open }: { pixie: Pixie; open: Open }) {
  const { state, actions } = useStore();
  const read = useHabits(pixie.id);
  const habits = state.habits[pixie.id];
  const [deleting, setDeleting] = useState<Habit | null>(null);
  return (
    <Page
      header={
        <PanelPageHeader
          title="Habits"
          back="Details"
          onBack={() => {
            open({ page: "details" });
          }}
        >
          <Button
            kind="plain"
            title="New habit"
            onClick={() => {
              open({ page: "habit", habit: null });
            }}
          >
            <PxGlyph name="plus" />
            New
          </Button>
        </PanelPageHeader>
      }
    >
      {!read && <DetailLine text="Could not read the habits" dim />}
      {read && habits !== undefined && (
        <>
          {habits.length === 0 && <DetailNote text={EMPTY_LIST} />}
          {habits.map((habit, index) => (
            <div key={habit.id}>
              {index > 0 && <hr className="pd-sep" />}
              <HabitRow
                habit={habit}
                open={open}
                onDelete={() => {
                  setDeleting(habit);
                }}
              />
            </div>
          ))}
          {habits.length > 0 && (
            <DetailNote text="Habits run while Nest runs on this computer and it is awake." />
          )}
        </>
      )}
      {deleting !== null && (
        <Confirm
          destructive
          title={`Delete ${deleting.name}?`}
          message="Its history goes too. Reports it made stay in the chat."
          action="Delete"
          onConfirm={() => {
            setDeleting(null);
            void actions.deleteHabit(deleting.pixie_id, deleting.id);
          }}
          onClose={() => {
            setDeleting(null);
          }}
        />
      )}
    </Page>
  );
}

function HabitRow({ habit, open, onDelete }: { habit: Habit; open: Open; onDelete: () => void }) {
  const { actions } = useStore();
  const now = useNow();
  const [menuOpen, setMenuOpen] = useState(false);
  const setEnabled = (enabled: boolean) =>
    void actions.updateHabit(habit.pixie_id, habit.id, { enabled });
  const edit = () => {
    open({ page: "habit", habit: habit.id });
  };
  const summary = habitSummary(habit);
  return (
    <div
      className={menuOpen ? "pd-habit menu" : "pd-habit"}
      role="group"
      aria-label={habit.name}
      onDoubleClick={edit}
    >
      <div className="pd-habit-h">
        <span className={habit.enabled ? "pd-habit-n" : "pd-habit-n off"}>{habit.name}</span>
        <span title={habit.enabled ? "On. Turn off to pause it" : "Paused. Turn on to resume it"}>
          <Toggle
            label={habit.enabled ? `Pause ${habit.name}` : `Resume ${habit.name}`}
            checked={habit.enabled}
            onChange={setEnabled}
          />
        </span>
      </div>
      {summary !== "" && <p className="pd-habit-s">{summary}</p>}
      <p className="pd-habit-runs">
        <StatusDot
          tone={habit.last_run === null ? "done" : OUTCOMES[habit.last_run.outcome].tone}
          hollow={habit.last_run === null}
        />
        <span>{lastRunText(habit.last_run, now)}</span>
        <span>·</span>
        <span>{nextRunText(habit, now)}</span>
      </p>
      <div className="pd-habit-b">
        <Button
          kind="plain"
          title="Run it now, whatever the schedule and usage"
          onClick={() => void actions.runHabit(habit.pixie_id, habit.id)}
        >
          <PxGlyph name="play" />
          Run now
        </Button>
        <Button
          kind="plain"
          title="Its latest runs"
          onClick={() => {
            open({ page: "history", habit: habit.id });
          }}
        >
          <PxGlyph name="clock" />
          History
        </Button>
        <span className="flex" />
        <RowActionsMenu
          title={habit.name}
          onOpenChange={setMenuOpen}
          items={() => [
            { title: "Edit", icon: "edit", onSelect: edit },
            {
              title: habit.enabled ? "Pause" : "Resume",
              icon: habit.enabled ? "pause" : "play",
              onSelect: () => {
                setEnabled(!habit.enabled);
              },
            },
            separator,
            { title: "Delete", icon: "trash", danger: true, onSelect: onDelete },
          ]}
        />
      </div>
    </div>
  );
}

/** New habit and Edit: name, instructions, schedule, triggers and the longest run. */
export function HabitEditor({
  pixie,
  habitId,
  open,
}: {
  pixie: Pixie;
  // The habit edited; null for a new one.
  habitId: string | null;
  open: Open;
}) {
  const { state, actions } = useStore();
  const habit =
    habitId === null ? undefined : state.habits[pixie.id]?.find((h) => h.id === habitId);
  const known = state.habits[pixie.id] !== undefined;
  // The draft once the habit is known; a new one starts at once.
  const [draft, setDraft] = useState<HabitDraft | null>(() =>
    habitId === null ? newDraft() : habit === undefined ? null : draftOf(habit),
  );
  const [saving, setSaving] = useState(false);
  const back = () => {
    open({ page: "habits" });
  };

  useEffect(() => {
    if (habitId !== null && !known) void actions.loadHabits(pixie.id);
  }, [actions, habitId, known, pixie.id]);
  // An edited habit read later fills the draft; one that is gone goes back to the list.
  if (draft === null && habit !== undefined) setDraft(draftOf(habit));
  const gone = habitId !== null && known && habit === undefined;
  useEffect(() => {
    if (gone) open({ page: "habits" });
  }, [gone, open]);

  const change = (patch: Partial<HabitDraft>) => {
    setDraft((before) => (before === null ? before : { ...before, ...patch }));
  };
  const problem = draft === null ? null : problemOf(draft);
  const save = () => {
    if (draft === null || !canSave(draft) || saving) return;
    setSaving(true);
    const done =
      habit === undefined
        ? actions.createHabit(pixie.id, createBody(draft)).then((created) => created !== null)
        : actions.updateHabit(pixie.id, habit.id, updateBody(draft, habit));
    void done.then((ok) => {
      setSaving(false);
      if (ok) back();
    });
  };

  return (
    <div
      className="pd-page"
      onKeyDown={(event) => {
        if (event.key === "s" && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          save();
        }
      }}
    >
      <PanelPageHeader
        title={habitId === null ? "New habit" : "Edit habit"}
        back="Habits"
        onBack={back}
      >
        <Button
          kind="primary"
          disabled={draft === null || !canSave(draft) || saving}
          title={problem ?? "Save the habit"}
          onClick={save}
        >
          Save
        </Button>
      </PanelPageHeader>
      <div className="pd-scroll">
        {draft !== null && (
          <>
            <DetailHeading title="Name" divided={false} />
            <input
              className="pd-field pd-name"
              aria-label="Name"
              placeholder="Morning check"
              value={draft.name}
              onChange={(event) => {
                change({ name: event.target.value });
              }}
            />
            <DetailHeading title="What to check and what is worth reporting" />
            <textarea
              className="pd-field pd-prompt"
              aria-label="Instructions"
              value={draft.prompt}
              onChange={(event) => {
                change({ prompt: event.target.value });
              }}
            />
            <DetailHeading title="Schedule" />
            <ScheduleRows draft={draft} change={change} />
            <DetailHeading title="Also runs when" />
            {TRIGGERS.map((trigger) => {
              const on = draft.triggers.includes(trigger.value);
              return (
                <button
                  key={trigger.value}
                  className="pd-check"
                  role="checkbox"
                  aria-checked={on}
                  onClick={() => {
                    change({
                      triggers: on
                        ? draft.triggers.filter((t) => t !== trigger.value)
                        : [...draft.triggers, trigger.value],
                    });
                  }}
                >
                  <CheckBox on={on} />
                  {trigger.label}
                </button>
              );
            })}
            <DetailNote text="In any project's chats. At most once in 5 minutes." />
            <GitHubRows
              draft={draft.github}
              change={(patch) => {
                change({ github: { ...draft.github, ...patch } });
              }}
            />
            <DetailHeading title="Limit" />
            <StepperRow
              title="Longest run"
              value={draft.maxMinutes}
              shown={`${String(draft.maxMinutes)} min`}
              min={MAX_MINUTES.min}
              max={MAX_MINUTES.max}
              onChange={(maxMinutes) => {
                change({ maxMinutes });
              }}
            />
            <DetailNote text="A longer run is stopped and recorded as timed out." />
            <div className="pd-stepper">
              <span className="pd-stepper-t">Autopilot</span>
              <Toggle
                label="Autopilot"
                checked={draft.autopilot}
                onChange={(autopilot) => {
                  change({ autopilot });
                }}
              />
            </div>
            {problem !== null && <p className="pd-problem">{problem}</p>}
          </>
        )}
      </div>
    </div>
  );
}

/** How often it repeats, then the minute, time or day that kind needs. */
function ScheduleRows({
  draft,
  change,
}: {
  draft: HabitDraft;
  change: (patch: Partial<HabitDraft>) => void;
}) {
  const two = (n: number) => String(n).padStart(2, "0");
  return (
    <>
      <PickerRow
        title="Repeats"
        value={REPEATS.find((r) => r.value === draft.repeats)?.label ?? ""}
        items={() =>
          REPEATS.map((kind) => ({
            title: kind.label,
            checked: draft.repeats === kind.value,
            onSelect: () => {
              change({ repeats: kind.value });
            },
          }))
        }
      />
      {draft.repeats === "hourly" && (
        <StepperRow
          title="At minute"
          value={draft.hourlyMinute}
          shown={`:${two(draft.hourlyMinute)}`}
          min={0}
          max={59}
          onChange={(hourlyMinute) => {
            change({ hourlyMinute });
          }}
        />
      )}
      {draft.repeats === "weekly" && (
        <PickerRow
          title="Day"
          value={WEEKDAY_NAMES[draft.weekday] ?? ""}
          items={() =>
            WEEKDAY_NAMES.map((name, day) => ({
              title: name,
              checked: draft.weekday === day,
              onSelect: () => {
                change({ weekday: day });
              },
            }))
          }
        />
      )}
      {(draft.repeats === "daily" ||
        draft.repeats === "weekdays" ||
        draft.repeats === "weekly") && (
        <div className="pd-timerow">
          <span>At</span>
          <TimeField
            hour={draft.hour}
            minute={draft.minute}
            onChange={(hour, minute) => {
              change({ hour, minute });
            }}
          />
        </div>
      )}
      {draft.repeats !== "never" && (
        <DetailNote text="In this computer's time. A run more than 2 hours late is skipped." />
      )}
    </>
  );
}

/**
 * A habit's latest runs, newest first: outcome, start, length and report title, with
 * Open transcript for runs that had a session.
 */
export function HabitHistory({
  pixie,
  habitId,
  open,
}: {
  pixie: Pixie;
  habitId: string;
  open: Open;
}) {
  const { state, actions } = useStore();
  const habit = state.habits[pixie.id]?.find((h) => h.id === habitId);
  const runs = state.habitRuns[habitId];
  const [failed, setFailed] = useState(false);
  const known = state.habits[pixie.id] !== undefined;
  useEffect(() => {
    let current = true;
    const load = async () => {
      if (!known) await actions.loadHabits(pixie.id);
      const loaded = await actions.loadHabitRuns(pixie.id, habitId);
      if (current) setFailed(loaded === null);
    };
    void load();
    return () => {
      current = false;
    };
  }, [actions, pixie.id, habitId, known]);
  return (
    <Page
      header={
        <PanelPageHeader
          title={habit?.name ?? "History"}
          back="Habits"
          onBack={() => {
            open({ page: "habits" });
          }}
        >
          {habit !== undefined && (
            <Button kind="plain" onClick={() => void actions.runHabit(pixie.id, habit.id)}>
              <PxGlyph name="play" />
              Run now
            </Button>
          )}
        </PanelPageHeader>
      }
    >
      {failed && <DetailLine text="Could not read the history" dim />}
      {!failed && runs !== undefined && (
        <>
          {runs.length === 0 && <DetailNote text={EMPTY_HISTORY} />}
          {runs.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </>
      )}
    </Page>
  );
}

function RunRow({ run }: { run: HabitRun }) {
  const shell = useShell();
  const now = useNow(30_000);
  const details = [runDuration(run, now), run.report_title ?? run.reason].filter(
    (part) => part !== null,
  );
  return (
    <div className="pd-run">
      <div className="pd-run-h">
        <StatusDot tone={OUTCOMES[run.outcome].tone} />
        <span className="pd-run-o">{OUTCOMES[run.outcome].label}</span>
        <span className="pd-time">{startedText(run, now)}</span>
      </div>
      {details.length > 0 && <p className="pd-run-d pd-select">{details.join(" · ")}</p>}
      {run.session_id !== null && (
        <button
          className="pd-link small"
          title="This run's chat, read-only"
          onClick={() => {
            if (run.session_id !== null) shell.openHabitRun(run.session_id);
          }}
        >
          Open transcript
        </button>
      )}
    </div>
  );
}
