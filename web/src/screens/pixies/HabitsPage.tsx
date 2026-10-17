import { useEffect, useState } from "react";
import type { Habit, HabitRun, Pixie } from "../../api/types.ts";
import { activityTime } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import { ActionSheet, Sheet } from "../../ui/Sheet.tsx";
import { AddHeading } from "./AddHeading.tsx";
import { Confirm } from "./Confirm.tsx";
import { HabitEditor } from "./HabitEditor.tsx";
import { HabitHistory } from "./HabitHistory.tsx";
import { outcomeText, scheduleText, triggersText } from "./habits.ts";

interface Props {
  pixie: Pixie;
  onClose: () => void;
  // A run's transcript, from its history.
  onOpenChat: (sessionId: string) => void;
}

// What is open over the list: a habit's menu, the editor, its history or its deletion.
type Over =
  | { menu: string }
  // The habit as it was when Edit was chosen; null for a new one.
  | { edit: Habit | null }
  | { history: string }
  | { remove: string };

/**
 * The pixie's habits (B42): each with its schedule, triggers, last run, next run and an
 * on switch; a habit's menu runs it now, pauses or resumes it, edits it, shows its history
 * or deletes it. Changes made elsewhere follow live.
 */
export function HabitsPage({ pixie, onClose, onOpenChat }: Props) {
  const { state, actions } = useStore();
  const { id } = pixie;
  const [loading, setLoading] = useState(true);
  const [over, setOver] = useState<Over | null>(null);
  const habits = state.habits[id];
  const close = () => {
    setOver(null);
  };
  const find = (habitId: string) => habits?.find((h) => h.id === habitId);
  const toggle = (habit: Habit) => {
    void actions.updateHabit(id, habit.id, { enabled: !habit.enabled });
  };

  useEffect(() => {
    void actions.loadHabits(id).then(() => {
      setLoading(false);
    });
  }, [actions, id]);

  const menu = over !== null && "menu" in over ? find(over.menu) : undefined;
  const editing = over !== null && "edit" in over ? over.edit : undefined;
  const history = over !== null && "history" in over ? find(over.history) : undefined;
  const removing = over !== null && "remove" in over ? find(over.remove) : undefined;

  return (
    <Sheet title="Habits" full onClose={onClose}>
      {habits !== undefined && (
        <AddHeading
          level={3}
          label="New habit"
          text="New"
          popup
          onAdd={() => {
            setOver({ edit: null });
          }}
        />
      )}
      {habits === undefined && loading && <p className="hint">Loading...</p>}
      {habits === undefined && !loading && <p className="hint">The habits could not be loaded.</p>}
      {habits?.length === 0 && (
        <p className="hint">
          No habits yet. A habit runs on a schedule or when something happens in your chats, and the
          pixie reports only what is worth it.
        </p>
      )}
      {habits !== undefined && habits.length > 0 && (
        <ul className="lgrp gl pxhabs">
          {habits.map((habit) => (
            <HabitRow
              key={habit.id}
              habit={habit}
              onMenu={() => {
                setOver({ menu: habit.id });
              }}
              onToggle={() => {
                toggle(habit);
              }}
            />
          ))}
        </ul>
      )}

      {menu !== undefined && (
        <HabitMenu
          habit={menu}
          onRun={() => void actions.runHabit(id, menu.id)}
          onToggle={() => {
            toggle(menu);
          }}
          onEdit={() => {
            setOver({ edit: menu });
          }}
          onHistory={() => {
            setOver({ history: menu.id });
          }}
          onDelete={() => {
            setOver({ remove: menu.id });
          }}
          onClose={close}
        />
      )}
      {editing !== undefined && (
        <HabitEditor
          habit={editing}
          onSave={(body) =>
            editing === null
              ? actions.createHabit(id, { ...body, enabled: true }).then((h) => h !== null)
              : actions.updateHabit(id, editing.id, body)
          }
          onClose={close}
        />
      )}
      {history !== undefined && (
        <HabitHistory habit={history} onOpenChat={onOpenChat} onClose={close} />
      )}
      {removing !== undefined && (
        <Confirm
          title={`Delete ${removing.name}?`}
          about="Its history goes with it. Runs waiting to start are cancelled."
          action="Delete"
          onConfirm={() => void actions.deleteHabit(id, removing.id)}
          onClose={close}
        />
      )}
    </Sheet>
  );
}

function HabitRow({
  habit,
  onMenu,
  onToggle,
}: {
  habit: Habit;
  onMenu: () => void;
  onToggle: () => void;
}) {
  const triggers = triggersText(habit.triggers);
  return (
    <li className="srow pxhab">
      <button className="pxdt pxhabb" aria-haspopup="menu" onClick={onMenu}>
        <b>{habit.name}</b>
        <span>{scheduleText(habit.schedule)}</span>
        {triggers !== "" && <span>{triggers}</span>}
        <small className="pxhabm">
          <LastRun run={habit.last_run} />
          <span>{nextText(habit)}</span>
        </small>
      </button>
      <button
        className="sw"
        role="switch"
        aria-checked={habit.enabled}
        aria-label={`${habit.name} on`}
        onClick={onToggle}
      />
    </li>
  );
}

/** "Reported 09:02", "Queued", or "Never run". */
function LastRun({ run }: { run: HabitRun | null }) {
  if (run === null) return <span>Never run</span>;
  const at = run.started_at ?? run.due_at;
  return (
    <span>
      <span>{outcomeText(run)}</span>
      {at !== null && run.outcome !== "queued" && <> {activityTime(at, new Date())}</>}
    </span>
  );
}

function nextText(habit: Habit): string {
  if (!habit.enabled) return "Paused";
  return habit.next_due_at === null ? "" : `Next ${activityTime(habit.next_due_at, new Date())}`;
}

interface MenuProps {
  habit: Habit;
  onRun: () => void;
  onToggle: () => void;
  onEdit: () => void;
  onHistory: () => void;
  onDelete: () => void;
  onClose: () => void;
}

function HabitMenu({ habit, onRun, onToggle, onEdit, onHistory, onDelete, onClose }: MenuProps) {
  const items: { label: string; run: () => void }[] = [
    { label: "Run now", run: onRun },
    { label: habit.enabled ? "Pause" : "Resume", run: onToggle },
    { label: "Edit", run: onEdit },
    { label: "History", run: onHistory },
  ];
  return (
    <ActionSheet label={`Actions for ${habit.name}`} title={<b>{habit.name}</b>} onClose={onClose}>
      {items.map((item) => (
        <button
          key={item.label}
          className="asi"
          role="menuitem"
          onClick={() => {
            onClose();
            item.run();
          }}
        >
          <span>{item.label}</span>
        </button>
      ))}
      <button className="asi dng" role="menuitem" onClick={onDelete}>
        <span>Delete…</span>
      </button>
    </ActionSheet>
  );
}
