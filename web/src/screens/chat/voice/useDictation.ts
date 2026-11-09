// The composer's mic for both clients (B154): tap to talk, tap again, and the words land
// where the caret is. The first tap asks to fetch voice input on the daemon's computer.
import { useEffect, useRef, useState } from "react";
import type { VoiceStatus } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { canRecord, startRecording, type Recording } from "./recorder.ts";

export type DictationPhase = "idle" | "starting" | "recording" | "working";

/** The question before fetching voice input, or after it failed. */
export interface VoiceSetup {
  title: string;
  about: string;
  action: string;
}

export interface Dictation {
  // False where this page cannot record (not a secure page, no microphone).
  available: boolean;
  phase: DictationPhase;
  installing: boolean;
  setup: VoiceSetup | null;
  toggle: () => void;
  confirmSetup: () => void;
  closeSetup: () => void;
}

// The daemon takes at most 5 minutes; stop just before.
const LONGEST_MS = 295_000;
const POLL_MS = 2000;

function size(mb: number): string {
  return mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${String(Math.round(mb / 10) * 10)} MB`;
}

/** What the mic button says it does now. */
export function dictateTitle(dictation: Dictation): string {
  if (dictation.phase === "working") return "Turning speech into text";
  if (dictation.phase !== "idle") return "Stop and turn into text";
  return dictation.installing ? "Voice input is downloading" : "Dictate";
}

/**
 * Where the words go: at the caret while the field has the keyboard, else at the end. A
 * field without the keyboard may hold a caret from long ago, or none.
 */
export function spokenAt(field: HTMLTextAreaElement | null, text: string): number {
  return field !== null && document.activeElement === field ? field.selectionStart : text.length;
}

export function setupQuestion(status: VoiceStatus, machine: string | null): VoiceSetup {
  if (status.state === "install_failed") {
    return {
      title: "Voice input could not be set up",
      about: status.detail ?? "The download stopped.",
      action: "Try again",
    };
  }
  const where = machine ?? "the computer Nest runs on";
  return {
    title: "Turn on voice input?",
    about:
      `Nest turns what you say into text on ${where}, with a free model that stays there. ` +
      `It needs a one-time download of about ${size(status.download_mb)}.`,
    action: "Download",
  };
}

export function microphoneProblem(error: unknown): string {
  const name = error instanceof DOMException ? error.name : "";
  if (name === "NotAllowedError") return "Nest is not allowed to use the microphone";
  if (name === "NotFoundError") return "No microphone was found";
  return "The microphone could not start";
}

/**
 * `onText` gets what was said; the latest one passed is used. `draft` names the draft the
 * words are for: when it changes (a pane showing another chat), a recording is dropped.
 */
export function useDictation(onText: (spoken: string) => void, draft: string): Dictation {
  const { state, actions } = useStore();
  const available = canRecord();
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [phase, setPhase] = useState<DictationPhase>("idle");
  const [setup, setSetup] = useState<VoiceSetup | null>(null);
  const recording = useRef<Recording | null>(null);
  const longest = useRef<number | undefined>(undefined);
  const mounted = useRef(false);
  // Read through a call: a check after an await must see the ref as it is then.
  const open = () => mounted.current;
  // Bumped by each start and each drop: a start or an answer from an older turn is let go.
  const turn = useRef(0);
  const deliver = useRef(onText);
  useEffect(() => {
    deliver.current = onText;
  });

  // Read as the composer opens and whenever the page comes back: it may have been removed
  // or its model changed from another device meanwhile.
  useEffect(() => {
    if (!available) return;
    let live = true;
    const load = () => {
      void actions.voiceStatus().then((found) => {
        if (live && found !== null) setStatus(found);
      });
    };
    load();
    window.addEventListener("focus", load);
    return () => {
      live = false;
      window.removeEventListener("focus", load);
    };
  }, [actions, available]);

  // While it downloads, follow it; say once when it is ready or failed.
  const installing = status?.state === "installing";
  useEffect(() => {
    if (!installing) return;
    const timer = window.setInterval(() => {
      void actions.voiceStatus().then((found) => {
        if (found === null || found.state === "installing") return;
        setStatus(found);
        if (found.state === "ready") actions.toast("Voice input is ready", "ok");
        else actions.toast("Voice input could not be set up", "error");
      });
    }, POLL_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [actions, installing]);

  const drop = () => {
    turn.current += 1;
    window.clearTimeout(longest.current);
    recording.current?.cancel();
    recording.current = null;
  };

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      drop();
    };
  }, []);

  // Another chat's draft: what was being said was for the one before.
  useEffect(
    () => () => {
      drop();
      setPhase("idle");
    },
    [draft],
  );

  const finish = async () => {
    window.clearTimeout(longest.current);
    const heard = recording.current;
    recording.current = null;
    if (heard === null) return;
    const mine = turn.current;
    setPhase("working");
    const text = await actions.transcribe(heard.stop());
    if (mine !== turn.current || !open()) return;
    setPhase("idle");
    if (text === null) {
      // Removed, or a model not downloaded yet: ask again rather than fail each time.
      const found = await actions.voiceStatus();
      if (found !== null && open()) {
        setStatus(found);
        if (found.state === "not_installed" || found.state === "install_failed") {
          setSetup(setupQuestion(found, state.machine));
        }
      }
      return;
    }
    if (text === "") actions.toast("Nothing was heard", "info");
    else deliver.current(text);
  };

  const toggle = () => {
    if (phase === "recording") {
      void finish();
      return;
    }
    if (phase === "starting") {
      // Waiting on the microphone; a tap gives up on it.
      drop();
      setPhase("idle");
      return;
    }
    if (phase !== "idle") return;
    if (status?.state !== "ready") {
      if (status === null) {
        void actions.voiceStatus().then((found) => {
          if (found === null) return;
          setStatus(found);
          if (found.state !== "ready" && found.state !== "installing") {
            setSetup(setupQuestion(found, state.machine));
          }
        });
      } else if (status.state === "installing") {
        actions.toast("Voice input is still downloading", "info");
      } else {
        setSetup(setupQuestion(status, state.machine));
      }
      return;
    }
    const failed = (error: unknown) => {
      setPhase("idle");
      actions.toast(microphoneProblem(error), "error");
    };
    turn.current += 1;
    const mine = turn.current;
    let starting: Promise<Recording>;
    try {
      starting = startRecording();
    } catch (error) {
      failed(error);
      return;
    }
    setPhase("starting");
    starting.then(
      (started) => {
        // Closed, given up on or moved to another chat while the microphone was asked for.
        if (!mounted.current || mine !== turn.current) {
          started.cancel();
          return;
        }
        recording.current = started;
        longest.current = window.setTimeout(() => void finish(), LONGEST_MS);
        setPhase("recording");
      },
      (error: unknown) => {
        if (mounted.current && mine === turn.current) failed(error);
      },
    );
  };

  return {
    available,
    phase,
    installing,
    setup,
    toggle,
    confirmSetup: () => {
      setSetup(null);
      void actions.installVoice().then((found) => {
        if (found !== null) setStatus(found);
      });
    },
    closeSetup: () => {
      setSetup(null);
    },
  };
}
