// Computer use (B150) for both clients: what a chat holds now, its latest screenshot, and
// the Settings page's state.
import { useEffect, useRef, useState } from "react";
import type {
  ComputerKind,
  ComputerPermission,
  ComputerStatus,
  ComputerUseSettings,
} from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { heldTargets, type HeldTarget } from "../../transcript/computer.ts";

/** What the chat holds now, from its stored `computer.state` events. */
export function useHeld(sessionId: string | undefined): readonly HeldTarget[] {
  const { state } = useStore();
  return heldTargets(sessionId === undefined ? undefined : state.transcripts[sessionId]);
}

/**
 * The chat's latest screenshot as an object URL, fetched again on each new `computer.frame`;
 * null until one loads. The API wants the device's credentials, so it is read as data. The
 * URL it replaces, and the last one when the screen goes, are let go.
 */
export function useFrame(sessionId: string): string | null {
  const { state, actions } = useStore();
  const seq = state.computerFrames[sessionId]?.seq ?? 0;
  const [url, setUrl] = useState<string | null>(null);
  const current = useRef<string | null>(null);
  useEffect(() => {
    let live = true;
    void actions.computerFrame(sessionId).then((blob) => {
      if (!live || blob === null) return;
      const previous = current.current;
      current.current = URL.createObjectURL(blob);
      setUrl(current.current);
      if (previous !== null) URL.revokeObjectURL(previous);
    });
    return () => {
      live = false;
    };
  }, [actions, sessionId, seq]);
  useEffect(
    () => () => {
      if (current.current !== null) URL.revokeObjectURL(current.current);
      current.current = null;
    },
    [],
  );
  return url;
}

/** Whether the chat waits on the user, for the live dot's colour. */
export function useWaiting(sessionId: string): boolean {
  const { state } = useStore();
  return Object.values(state.approvals).some(
    (a) => a.session_id === sessionId && a.status === "pending",
  );
}

/**
 * Settings > Computer use: the settings with a save that shows at once, and what the Mac
 * can reach, read again when the page comes back into view, as after System Settings.
 */
export function useComputerPage() {
  const { state, actions } = useStore();
  const settings = state.settings.computer;
  const [status, setStatus] = useState<ComputerStatus | null>(null);
  // Bumped after asking macOS, which reads the status again.
  const [asked, setAsked] = useState(0);
  useEffect(() => {
    let live = true;
    const load = () => {
      void actions.computerStatus().then((found) => {
        if (live && found !== null) setStatus(found);
      });
    };
    load();
    window.addEventListener("focus", load);
    return () => {
      live = false;
      window.removeEventListener("focus", load);
    };
  }, [actions, asked]);
  return {
    settings,
    status,
    save: (change: Partial<ComputerUseSettings>) => {
      if (settings !== null)
        void actions.saveSection("computer", { ...settings, ...change }, settings);
    },
    ask: async (name: ComputerPermission) => {
      await actions.askComputerPermission(name);
      setAsked((n) => n + 1);
    },
  };
}

// macOS gives the nested helper the outer app's Screen Recording, so that row names Nest.
export const PERMISSIONS: readonly [ComputerPermission, string][] = [
  ["accessibility", "Accessibility for Nest Computer"],
  ["screen_recording", "Screen Recording for Nest"],
];

export const BLOCKED = "Blocked in System Settings.";

// The kinds besides the Mac's own apps, as Settings lists them, with where to get them.
export const KINDS: readonly { kind: ComputerKind; label: string; get: string }[] = [
  { kind: "ios", label: "iOS Simulator", get: "Get Xcode" },
  { kind: "android", label: "Android Emulator", get: "Get Android Studio" },
  { kind: "browser", label: "Shared browser", get: "Get it" },
];
