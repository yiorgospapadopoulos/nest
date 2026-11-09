import type { Api } from "../api/client.ts";
import type { VoiceModelId, VoiceStatus } from "../api/types.ts";

interface Tools {
  attempt: <T>(call: () => Promise<T>) => Promise<T | null>;
  quietly: <T>(call: () => Promise<T>) => Promise<T | null>;
}

/**
 * Voice input (B154): speech to text on the daemon's computer, for the phone and the Linux
 * app, which have no dictation of their own in Nest. Each failure is a toast, except reading
 * the state, which a composer does quietly as it opens.
 */
export function voiceActions(api: Api, { attempt, quietly }: Tools) {
  return {
    voiceStatus(): Promise<VoiceStatus | null> {
      return quietly(() => api.voiceStatus());
    },
    installVoice(): Promise<VoiceStatus | null> {
      return attempt(() => api.installVoice());
    },
    removeVoice(): Promise<VoiceStatus | null> {
      return attempt(() => api.removeVoice());
    },
    saveVoiceModel(model: VoiceModelId | null): Promise<VoiceStatus | null> {
      return attempt(() => api.saveVoiceModel(model));
    },
    /** What was said; null, after a toast, when it could not be turned into text. */
    async transcribe(recording: Blob): Promise<string | null> {
      const said = await attempt(() => api.transcribe(recording));
      return said?.text ?? null;
    },
  };
}
