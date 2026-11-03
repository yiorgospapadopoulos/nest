import { useEffect, useRef, useState } from "react";
import type { Approval } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { deviceStorage } from "../../store/legacyKeys.ts";
import { useBridge } from "../context.ts";
import { LAND_MS, latestRuns, loadIslandSettings, markSeen, seenDelay } from "../islandData.ts";
import {
  focusedChat,
  loadPreferences,
  loadSound,
  notificationFor,
  pillShows,
  visibleChats,
  windowActive,
  type Notice,
} from "../notifications.ts";
import type { Shell } from "./context.ts";
import { unfoldApproval } from "./frame/foldRows.ts";

const pageState = () => ({
  focused: document.hasFocus(),
  pageVisible: document.visibilityState === "visible",
});

/**
 * Whether the window is focused and its page shown, kept as focus, blur and visibility
 * change. The window manager's minimised and hidden states are asked where it matters,
 * when a notice comes (windowActive).
 */
function useWindowFocused(): boolean {
  const [focused, setFocused] = useState(() => {
    const page = pageState();
    return page.focused && page.pageVisible;
  });
  useEffect(() => {
    const update = () => {
      const page = pageState();
      setFocused(page.focused && page.pageVisible);
    };
    const off = () => {
      setFocused(false);
    };
    window.addEventListener("focus", update);
    window.addEventListener("blur", off);
    document.addEventListener("visibilitychange", update);
    return () => {
      window.removeEventListener("focus", update);
      window.removeEventListener("blur", off);
      document.removeEventListener("visibilitychange", update);
    };
  }, []);
  return focused;
}

/**
 * What the main window tells the rest of the desktop app as it changes: the chat focused
 * in it counts as seen for the pill (B114), the pill's clicks open where they point, and
 * the daemon's notices become notifications unless their chat is on screen.
 */
export function useWindowWatch(shell: Shell) {
  const { state, actions } = useStore();
  const bridge = useBridge();
  const storage = deviceStorage();
  const focused = useWindowFocused();
  const pixies = Object.values(state.pixies);
  const pixiesTab = shell.project === null;
  const chat = focusedChat(focused, shell.state, pixiesTab, pixies);

  // Seen once focused, after any pixie that just finished there has landed on the pill, and
  // again a moment after anything about it changes.
  const groups = chat === null ? undefined : state.pixieGroups[chat];
  const asking = Object.values(state.approvals).filter((a) => a.session_id === chat).length;
  useEffect(() => {
    if (chat === null) return;
    const landing = seenDelay(groups, Date.now());
    if (landing === 0) markSeen(storage, chat, Date.now());
    const timer = window.setTimeout(
      () => {
        markSeen(storage, chat, Date.now());
      },
      landing === 0 ? LAND_MS : landing,
    );
    return () => {
      window.clearTimeout(timer);
    };
  }, [storage, chat, groups, asking]);

  // Habit runs' chats, whose approvals the pill shows as needs you.
  const habitRunChats = new Set([
    ...Object.values(state.sessions).flatMap((s) => (s.habit_run_id == null ? [] : [s.id])),
    ...latestRuns(state).flatMap((r) => r.session_id ?? []),
  ]);
  const latest = useRef({
    shell,
    focused,
    pixies,
    sessions: state.sessions,
    pending: state.approvals,
    habitRunChats,
  });
  useEffect(() => {
    latest.current = {
      shell,
      focused,
      pixies,
      sessions: state.sessions,
      pending: state.approvals,
      habitRunChats,
    };
  });
  // The latest approval of each chat, from its event, which comes just before its notice.
  const approvals = useRef(new Map<string, Approval>());

  useEffect(
    () =>
      bridge.onOpenRequest((target) => {
        const s = latest.current.shell;
        if ("chat" in target) {
          s.openChat(target.chat);
          const repo = latest.current.sessions[target.chat]?.repo;
          if (target.approval !== undefined && repo !== undefined) {
            s.showNeedsYou(repo);
            // Its Needs you row opens too, as the Mac's island click does.
            const pending = latest.current.pending[target.approval];
            if (pending !== undefined) unfoldApproval(pending);
          }
        } else if ("pixie" in target) s.openPixie(target.pixie);
        else if ("habitRun" in target) s.openHabitRun(target.habitRun);
      }),
    [bridge],
  );

  useEffect(
    () =>
      actions.onEvent((event) => {
        if (event.type === "approval.created") {
          const approval = event.payload.approval as unknown as Approval;
          approvals.current.set(approval.session_id, approval);
          return;
        }
        if (event.type !== "notify") return;
        const now = latest.current;
        const notice = event.payload as unknown as Notice;
        const pillOn = loadIslandSettings(storage).shown;
        const asked = approvals.current.get(notice.session_id);
        if (pillShows(notice, pillOn, asked, now.habitRunChats)) return;
        void bridge.windowState().then((manager) => {
          const active = windowActive({
            focused: now.focused,
            pageVisible: document.visibilityState === "visible",
            minimized: manager?.minimized ?? null,
            shown: manager?.visible ?? null,
          });
          const shown = visibleChats(
            active,
            now.shell.state,
            now.shell.project === null,
            now.pixies,
          );
          const content = notificationFor(notice, loadPreferences(storage), shown, now.pixies);
          if (content === null) return;
          void bridge.notify(content.title, content.body, content.chat, loadSound(storage));
        });
      }),
    [actions, bridge, storage],
  );
}
