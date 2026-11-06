// Which of the daemon's `notify` events become desktop notifications, and what they say,
// ported from NestKit's NotificationPolicy.swift: one switch per kind, kept on this device,
// and nothing about a chat the user is looking at right now.
import type { Approval, NotifyKind, Pixie } from "../api/types.ts";
import type { ProjectState } from "./layout/project.ts";

export type NotificationPreferences = Record<NotifyKind, boolean>;

/** The Notify me about switches in order, named as on the Mac. */
export const NOTIFY_TOGGLES: { kind: NotifyKind; title: string }[] = [
  { kind: "needs_approval", title: "Approvals" },
  { kind: "question", title: "Questions" },
  { kind: "review_ready", title: "Work ready for review" },
  { kind: "failed", title: "Agent errors" },
  { kind: "finished", title: "Finished turns" },
  { kind: "ci_failed", title: "Pull request checks failed" },
  { kind: "ready_to_merge", title: "Pull requests ready to merge" },
  { kind: "stuck", title: "Chats that look stuck" },
  { kind: "pixie_report", title: "Pixie reports" },
  { kind: "pixie_waiting", title: "Pixies waiting on you" },
  { kind: "usage_limit", title: "Usage limit pauses" },
];

export const NOTIFY_KEY = "nest.desktop.notifications";

export function loadPreferences(storage: Storage): NotificationPreferences {
  let saved: Record<string, unknown> = {};
  try {
    saved = JSON.parse(storage.getItem(NOTIFY_KEY) ?? "{}") as Record<string, unknown>;
  } catch {
    saved = {};
  }
  return Object.fromEntries(
    NOTIFY_TOGGLES.map(({ kind }) => [kind, saved[kind] !== false]),
  ) as NotificationPreferences;
}

export function savePreferences(storage: Storage, preferences: NotificationPreferences): void {
  try {
    storage.setItem(NOTIFY_KEY, JSON.stringify(preferences));
  } catch {
    // A blocked storage keeps the switches for this run only.
  }
}

// Whether notifications play the system's sound; off until switched on, as on the Mac.
export const SOUND_KEY = "nest.desktop.notificationSound";

export function loadSound(storage: Storage): boolean {
  try {
    return storage.getItem(SOUND_KEY) === "on";
  } catch {
    return false;
  }
}

export function saveSound(storage: Storage, on: boolean): void {
  try {
    storage.setItem(SOUND_KEY, on ? "on" : "off");
  } catch {
    // A blocked storage keeps the switch for this run only.
  }
}

/** A `notify` event's payload (daemon/src/nestd/notifications/notifier.py). */
export interface Notice {
  kind: string;
  session_id: string;
  repo: string;
  title: string;
  text: string;
  pixie_name?: string;
}

// Review comments wait in Needs you like an approval and share its switch (B101).
const SWITCH_OF: Record<string, NotifyKind | undefined> = { review_comments: "needs_approval" };

function wants(preferences: NotificationPreferences, kind: string): boolean {
  const own = SWITCH_OF[kind] ?? (kind in preferences ? (kind as NotifyKind) : undefined);
  return own !== undefined && preferences[own];
}

/** The project a notice comes from, or the pixie's name for a pixie chat (D072). */
function source(notice: Notice, pixies: Pixie[]): string {
  if (!notice.repo.startsWith("pixie:")) return notice.repo;
  const id = notice.repo.slice("pixie:".length);
  return pixies.find((p) => p.id === id)?.name ?? "Pixie";
}

// The approvals that stop a call until the user answers, which the pill shows as needs you.
const BLOCKING = new Set<Approval["kind"]>(["permission", "question", "plan"]);

/**
 * Whether the pill already shows what a notice is about, so no notification goes out while
 * it is on (user, 2026-11-03): an approval raised inside a pixie call, or in a habit run's
 * chat, which the pill shows as needs you. The pill shows no normal chat (as the Mac's
 * island), and called pixies and habit runs send no finished notices, so every other notice
 * still goes out.
 */
export function pillShows(
  notice: Notice,
  pillOn: boolean,
  approval: Approval | undefined,
  habitRunChats: Set<string>,
): boolean {
  if (!pillOn || approval === undefined) return false;
  if (notice.kind !== "needs_approval" && notice.kind !== "question") return false;
  if (approval.session_id !== notice.session_id || !BLOCKING.has(approval.kind)) return false;
  return typeof approval.payload.call === "string" || habitRunChats.has(notice.session_id);
}

/** The chat a click on the notification opens; none for a notice about no chat. */
function chatOf(notice: Notice): { chat?: string } {
  return notice.session_id === "" ? {} : { chat: notice.session_id };
}

/** Switched-on notices, unless the user is looking at that chat right now. */
export function notificationFor(
  notice: Notice,
  preferences: NotificationPreferences,
  visibleChats: Set<string>,
  pixies: Pixie[],
): { title: string; body: string; chat?: string } | null {
  if (!wants(preferences, notice.kind) || visibleChats.has(notice.session_id)) return null;
  // A pixie's report: titled with the pixie, its body the report's title (B42).
  if (notice.kind === "pixie_report") {
    return {
      title: notice.pixie_name ?? source(notice, pixies),
      body: notice.title,
      ...chatOf(notice),
    };
  }
  return {
    title: `${source(notice, pixies)} · ${notice.title}`,
    body: notice.text,
    ...chatOf(notice),
  };
}

/** What the window and the window manager say about the main window. */
export interface WindowState {
  // The web page has the keyboard focus (focus and blur).
  focused: boolean;
  // document.visibilityState is "visible".
  pageVisible: boolean;
  // From the window manager; null when it cannot tell.
  minimized: boolean | null;
  shown: boolean | null;
}

/**
 * Whether the user can be looking at the window, as the Mac's NSApp.isActive with a key
 * window: focused, and neither minimised nor hidden. On X11 a minimised window can still
 * report the focus, so focus alone is not enough.
 */
export function windowActive(window: WindowState): boolean {
  return (
    window.focused && window.pageVisible && window.minimized !== true && window.shown !== false
  );
}

/**
 * The chats on screen in the focused window: the shown project's open panes while its
 * workspace shows (the maximized one alone), or on the Pixies tab the chats of the pixie
 * panes on screen.
 */
export function visibleChats(
  windowFocused: boolean,
  shown: ProjectState,
  pixiesTab: boolean,
  pixies: Pixie[],
): Set<string> {
  if (!windowFocused) return new Set();
  const { layout } = shown;
  const panes = layout.maximized === null ? layout.leaves : [layout.maximized];
  if (pixiesTab) {
    return new Set(panes.flatMap((id) => pixies.find((p) => p.id === id)?.chat_session_id ?? []));
  }
  return shown.view === "workspace" ? new Set(panes) : new Set();
}

/** The chat the user is on: the focused pane's, in the focused window (B114's seen rule). */
export function focusedChat(
  windowFocused: boolean,
  shown: ProjectState,
  pixiesTab: boolean,
  pixies: Pixie[],
): string | null {
  if (!windowFocused) return null;
  const pane = shown.layout.maximized ?? shown.layout.focused;
  if (pane === null) return null;
  if (pixiesTab) return pixies.find((p) => p.id === pane)?.chat_session_id ?? null;
  return shown.view === "workspace" ? pane : null;
}
