import { useId, useState } from "react";
import type { Habit, HabitBody, HabitSchedule, HabitTrigger } from "../../api/types.ts";
import { Sheet } from "../../ui/Sheet.tsx";
import { SCHEDULE_KINDS, TRIGGERS, WEEKDAYS, type ScheduleKind } from "./habits.ts";

const NONE = "none";
const DEFAULT_TIME = "09:00";
const DEFAULT_MINUTES = 20;
// The daemon's limits (B42).
const MAX_NAME = 60;
const MAX_PROMPT = 4000;
const MAX_MINUTES = 120;

interface Props {
  // Null for a new habit.
  habit: Habit | null;
  // Resolves to whether the Mac saved it; the editor stays open when it did not.
  onSave: (body: HabitBody) => Promise<boolean>;
  onClose: () => void;
}

/** An integer from the text field within `min` and `max`, else null. */
function whole(text: string, min: number, max: number): number | null {
  const value = Number(text);
  return text.trim() !== "" && Number.isInteger(value) && value >= min && value <= max
    ? value
    : null;
}

/**
 * New habit and Edit habit: a name, what to check, a schedule with its time fields, the
 * triggers and the longest run. A habit needs a schedule or a trigger.
 */
export function HabitEditor({ habit, onSave, onClose }: Props) {
  const id = useId();
  const schedule = habit?.schedule ?? null;
  const [name, setName] = useState(habit?.name ?? "");
  const [prompt, setPrompt] = useState(habit?.prompt ?? "");
  const [kind, setKind] = useState<ScheduleKind | typeof NONE>(schedule?.kind ?? NONE);
  const [minute, setMinute] = useState(schedule?.kind === "hourly" ? String(schedule.minute) : "0");
  const [time, setTime] = useState(
    schedule !== null && "time" in schedule ? schedule.time : DEFAULT_TIME,
  );
  const [weekday, setWeekday] = useState(schedule?.kind === "weekly" ? schedule.weekday : 0);
  const [triggers, setTriggers] = useState<ReadonlySet<HabitTrigger>>(
    new Set(habit?.triggers ?? []),
  );
  const [limit, setLimit] = useState(String(habit?.max_minutes ?? DEFAULT_MINUTES));
  const [saving, setSaving] = useState(false);

  const minuteValue = whole(minute, 0, 59);
  const limitValue = whole(limit, 1, MAX_MINUTES);
  const planned: HabitSchedule | null = (() => {
    switch (kind) {
      case NONE:
        return null;
      case "hourly":
        return { kind, minute: minuteValue ?? 0 };
      case "weekly":
        return { kind, weekday, time };
      default:
        return { kind, time };
    }
  })();
  const chosen = (Object.keys(TRIGGERS) as HabitTrigger[]).filter((t) => triggers.has(t));
  const when = planned !== null || chosen.length > 0;
  // What Save sends; null while something is missing.
  const body: HabitBody | null =
    name.trim() !== "" &&
    prompt.trim() !== "" &&
    when &&
    limitValue !== null &&
    (kind !== "hourly" || minuteValue !== null)
      ? {
          name: name.trim(),
          prompt: prompt.trim(),
          schedule: planned,
          triggers: chosen,
          max_minutes: limitValue,
        }
      : null;

  const save = async (ready: HabitBody) => {
    setSaving(true);
    const saved = await onSave(ready);
    setSaving(false);
    if (saved) onClose();
  };
  const toggle = (trigger: HabitTrigger) => {
    const next = new Set(triggers);
    if (!next.delete(trigger)) next.add(trigger);
    setTriggers(next);
  };

  return (
    <Sheet
      title={habit === null ? "New habit" : "Edit habit"}
      full
      onClose={onClose}
      leading={
        <button className="done l" onClick={onClose}>
          Cancel
        </button>
      }
      trailing={
        <button
          className="done"
          disabled={body === null || saving}
          onClick={body === null ? undefined : () => void save(body)}
        >
          Save
        </button>
      }
    >
      <div className="pset pxhabe">
        <label htmlFor={`${id}-name`}>Name</label>
        <input
          id={`${id}-name`}
          className="rin2"
          value={name}
          maxLength={MAX_NAME}
          autoComplete="off"
          data-autofocus
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
        <label htmlFor={`${id}-prompt`}>What to check</label>
        <textarea
          id={`${id}-prompt`}
          className="rin2"
          rows={5}
          value={prompt}
          maxLength={MAX_PROMPT}
          placeholder="What to look at, and what is worth reporting"
          onChange={(event) => {
            setPrompt(event.target.value);
          }}
        />
      </div>

      <div className="lgrp gl pxgap">
        <div className="srow">
          <label htmlFor={`${id}-kind`}>Schedule</label>
          <select
            id={`${id}-kind`}
            className="ssel"
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as ScheduleKind | typeof NONE);
            }}
          >
            <option value={NONE}>No schedule</option>
            {Object.entries(SCHEDULE_KINDS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        {kind === "hourly" && (
          <div className="srow qh">
            <label>
              Minute
              <input
                type="number"
                inputMode="numeric"
                min={0}
                max={59}
                value={minute}
                onChange={(event) => {
                  setMinute(event.target.value);
                }}
              />
            </label>
          </div>
        )}
        {kind === "weekly" && (
          <div className="srow">
            <label htmlFor={`${id}-day`}>Day</label>
            <select
              id={`${id}-day`}
              className="ssel"
              value={weekday}
              onChange={(event) => {
                setWeekday(Number(event.target.value));
              }}
            >
              {WEEKDAYS.map((day, index) => (
                <option key={day} value={index}>
                  {day}
                </option>
              ))}
            </select>
          </div>
        )}
        {kind !== NONE && kind !== "hourly" && (
          <div className="srow qh">
            <label>
              Time
              <input
                type="time"
                value={time}
                onChange={(event) => {
                  // An emptied field keeps the last time.
                  if (event.target.value !== "") setTime(event.target.value);
                }}
              />
            </label>
          </div>
        )}
      </div>

      <h3 className="pg-h">Also run</h3>
      <div className="lgrp gl">
        {(Object.entries(TRIGGERS) as [HabitTrigger, string][]).map(([trigger, words]) => (
          <label key={trigger} className="srow pxchk">
            <span id={`${id}-${trigger}`}>When {words}</span>
            <input
              type="checkbox"
              aria-labelledby={`${id}-${trigger}`}
              checked={triggers.has(trigger)}
              onChange={() => {
                toggle(trigger);
              }}
            />
          </label>
        ))}
      </div>
      <p className="hint gnote">
        {when
          ? "Triggers count only chats in the pixie's projects."
          : "Choose a schedule or a trigger."}
      </p>

      <div className="lgrp gl pxgap">
        <div className="srow qh">
          <label>
            Longest run, in minutes
            <input
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_MINUTES}
              value={limit}
              onChange={(event) => {
                setLimit(event.target.value);
              }}
            />
          </label>
        </div>
      </div>
    </Sheet>
  );
}
