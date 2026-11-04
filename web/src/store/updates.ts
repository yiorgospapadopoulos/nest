import { useRef, useState } from "react";
import type { EngineUpdate } from "../api/types.ts";
import { useStore } from "./context.ts";
import type { State, UpdatesState } from "./state.ts";

export interface ReadyUpdate {
  engines: EngineUpdate[];
  relaunching: boolean;
}

export type UpdateStrip = { kind: "notice"; text: string } | ({ kind: "ready" } & ReadyUpdate);

/** An update that can be relaunched into, or is being: what Settings' row shows. */
export function readyUpdate({ status, restarting }: UpdatesState): ReadyUpdate | null {
  if (restarting === "undo") return null;
  if (restarting === "relaunch") return { engines: status?.engines ?? [], relaunching: true };
  return status?.state === "ready" ? { engines: status.engines, relaunching: false } : null;
}

/** What the strip shows, if anything: a notice wins until dismissed; an undo shows none. */
export function updateStrip(updates: UpdatesState): UpdateStrip | null {
  const { status, restarting, hidden } = updates;
  if (restarting === null && status !== null && status.notice !== null) {
    return { kind: "notice", text: status.notice };
  }
  const ready = readyUpdate(updates);
  return ready === null || hidden ? null : { kind: "ready", ...ready };
}

/**
 * The connection counts as lost unless this app asked for the restart that dropped it:
 * the page loads again when the daemon is back, so nothing warns meanwhile.
 */
export function connectionLost({ reconnecting, updates }: State): boolean {
  return reconnecting && updates.restarting === null;
}

export function engineChange({ name, current, new: next }: EngineUpdate): string {
  return `${name} ${current} → ${next}`;
}

/** One line per engine, for a Settings value. */
export function engineChanges(engines: EngineUpdate[]): string {
  return engines.map(engineChange).join("\n");
}

export type UpdateRestart = "relaunch" | "undo";

const QUESTIONS: Record<UpdateRestart, { title: string; action: string; idle: string }> = {
  relaunch: { title: "Relaunch to update?", action: "Relaunch", idle: "" },
  undo: {
    title: "Undo update?",
    action: "Undo update",
    idle: "Nest relaunches on the engines from before.",
  },
};

/** The confirmation before a restart that would stop `busy` chats. */
export function restartQuestion(kind: UpdateRestart, busy: number) {
  const { title, action, idle } = QUESTIONS[kind];
  const about =
    busy === 0
      ? idle
      : busy === 1
        ? "1 chat is mid-turn. It will stop and can be resumed."
        : `${String(busy)} chats are mid-turn. They will stop and can be resumed.`;
  return { title, action, about };
}

/**
 * Relaunch or Undo as a button runs it: Relaunch goes straight on when no chat would stop,
 * otherwise `asking` holds the chats mid-turn until `confirm` or `cancel`.
 */
export function useUpdateRestart(kind: UpdateRestart) {
  const { state, actions } = useStore();
  const [asking, setAsking] = useState<number | null>(null);
  const reading = useRef(false);
  const confirm = () => {
    setAsking(null);
    void (kind === "relaunch" ? actions.relaunchUpdate() : actions.undoUpdate());
  };
  const start = async () => {
    if (reading.current) return;
    reading.current = true;
    const busy = await actions.busyChats();
    reading.current = false;
    if (busy > 0 || kind === "undo") setAsking(busy);
    else confirm();
  };
  const cancel = () => {
    setAsking(null);
  };
  return { asking, start, confirm, cancel, restarting: state.updates.restarting };
}
