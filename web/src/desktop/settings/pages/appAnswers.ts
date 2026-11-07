import type { SetupCheck } from "../../../api/types.ts";
import type { Bridge } from "../../bridge.ts";

/**
 * The checks only the app can make, for the bug report (B130): on Linux, whether anything
 * shows the notifications. The daemon puts these in place of its "Checked in the app."
 * The browser has nothing to say.
 */
export async function appAnswers(bridge: Bridge): Promise<SetupCheck[]> {
  if (!bridge.native) return [];
  const server = await bridge.notificationServer().catch(() => null);
  const shown = server !== null;
  return [
    {
      id: "notifications",
      title: "Notifications",
      state: shown ? "ok" : "missing",
      message: shown ? "" : "No notification service answers on this desktop.",
      detail: server,
      fix: null,
      importance: "recommended",
      stage: null,
      rank: shown ? 4 : 1,
    },
  ];
}
