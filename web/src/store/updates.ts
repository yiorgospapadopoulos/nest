import { useRef, useState } from "react";
import type { AppUpdate, EngineUpdate } from "../api/types.ts";
import { useStore } from "./context.ts";
import type { State, UpdatesState } from "./state.ts";

export interface ReadyUpdate {
  // A new Nest; always null on the phone.
  app: AppUpdate | null;
  engines: EngineUpdate[];
  relaunching: boolean;
}

// An app update starts only from the Mac and Linux apps; the phone never offers one (B130).
export type UpdateOffer = "app" | "phone";

export type UpdateStrip = { kind: "notice"; text: string } | ({ kind: "ready" } & ReadyUpdate);

/** An update that can be relaunched into, or is being: what Settings' row shows. */
export function readyUpdate(
  { status, restarting }: UpdatesState,
  offer: UpdateOffer,
): ReadyUpdate | null {
  if (restarting === "undo") return null;
  const app = offer === "app" ? (status?.app ?? null) : null;
  const engines = status?.engines ?? [];
  if (restarting === "relaunch") return { app, engines, relaunching: true };
  if (status?.state !== "ready" || (app === null && engines.length === 0)) return null;
  return { app, engines, relaunching: false };
}

/** What the strip shows, if anything: a notice wins until dismissed; an undo shows none. */
export function updateStrip(updates: UpdatesState, offer: UpdateOffer): UpdateStrip | null {
  const { status, restarting, hidden } = updates;
  if (restarting === null && status !== null && status.notice !== null) {
    return { kind: "notice", text: status.notice };
  }
  const ready = readyUpdate(updates, offer);
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

export function appChange({ version }: AppUpdate): string {
  return `Nest ${version}`;
}

/** One line for Nest and for each engine, for a Settings value. */
export function updateChanges({ app, engines }: ReadyUpdate): string {
  return [...(app === null ? [] : [appChange(app)]), ...engines.map(engineChange)].join("\n");
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
 * otherwise `asking` holds the chats mid-turn until `confirm` or `cancel`. `after` follows
 * a relaunch the daemon took (updateActions' relaunchUpdate).
 */
export function useUpdateRestart(kind: UpdateRestart, after?: () => Promise<unknown>) {
  const { state, actions } = useStore();
  const [asking, setAsking] = useState<number | null>(null);
  const reading = useRef(false);
  const confirm = () => {
    setAsking(null);
    void (kind === "relaunch" ? actions.relaunchUpdate(after) : actions.undoUpdate());
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
