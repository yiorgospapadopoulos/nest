// Settings > General > Voice input for both clients (B154): the model, its download, and
// removing it.
import { useEffect, useState } from "react";
import type { VoiceModelId, VoiceStatus } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";

const POLL_MS = 2000;

export type VoiceTone = "ok" | "run" | "bad" | "idle";

/** What the state row says, and its colour. */
export function voiceStateLabel(status: VoiceStatus): { label: string; tone: VoiceTone } {
  switch (status.state) {
    case "ready":
      return { label: "Ready", tone: "ok" };
    case "installing":
      return {
        label: status.step === "model" ? "Downloading the model..." : "Downloading...",
        tone: "run",
      };
    case "install_failed":
      return { label: "Could not download", tone: "bad" };
    case "not_installed":
      return { label: "Not downloaded", tone: "idle" };
  }
}

/** The model menu: each with its size, the computer's default named. */
export function modelChoices(status: VoiceStatus): { value: VoiceModelId; label: string }[] {
  return status.models.map((model) => {
    const size =
      model.size_mb >= 1000
        ? `${(model.size_mb / 1000).toFixed(1)} GB`
        : `${String(model.size_mb)} MB`;
    const named = model.id === status.default_model ? `${model.label} (default)` : model.label;
    return { value: model.id, label: `${named}, ${size}` };
  });
}

export function useVoiceSettings() {
  const { actions } = useStore();
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const keep = (found: VoiceStatus | null) => {
    if (found !== null) setStatus(found);
  };

  useEffect(() => {
    let live = true;
    void actions.voiceStatus().then((found) => {
      if (live && found !== null) setStatus(found);
    });
    return () => {
      live = false;
    };
  }, [actions]);

  const installing = status?.state === "installing";
  useEffect(() => {
    if (!installing) return;
    const timer = window.setInterval(() => {
      void actions.voiceStatus().then((found) => {
        if (found !== null) setStatus(found);
      });
    }, POLL_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [actions, installing]);

  return {
    status,
    /** The computer's default is saved as no choice, so it follows a new default. */
    choose: (model: VoiceModelId) => {
      void actions.saveVoiceModel(model === status?.default_model ? null : model).then(keep);
    },
    download: () => {
      void actions.installVoice().then(keep);
    },
    remove: () => {
      void actions.removeVoice().then(keep);
    },
  };
}
