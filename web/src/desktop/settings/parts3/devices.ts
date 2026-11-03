import type { ListedDevice } from "../../../api/types.ts";
import { ago } from "../../../format.ts";

// The words and rules of Settings > Devices, as NestKit's DevicesStore. On Linux the Mac's
// "This Mac" reads "This computer".

export const THIS_COMPUTER = "This computer";

/** Devices that are not revoked, this computer's first. */
export function shownDevices(devices: readonly ListedDevice[]): ListedDevice[] {
  const active = devices.filter((d) => d.revoked_at === null);
  return [...active.filter((d) => d.is_local), ...active.filter((d) => !d.is_local)];
}

// The name the daemon gave this machine's device before it named it for the platform.
const OLD_LOCAL_NAME = "This Mac";

/**
 * A device's name. This machine's device keeps a name it was given, but one stored as the
 * daemon's old default, "This Mac", reads "This computer" here.
 */
export function deviceTitle(device: ListedDevice): string {
  return device.is_local && device.name === OLD_LOCAL_NAME ? THIS_COMPUTER : device.name;
}

/** "This computer" for this one's device, else when it was last seen. */
export function deviceDetail(device: ListedDevice, now: Date): string {
  if (device.is_local || device.this_device) return THIS_COMPUTER;
  if (device.last_seen_at === null) return "Not seen yet";
  const elapsed = ago(device.last_seen_at, now);
  return elapsed === "now" ? "Last seen now" : `Last seen ${elapsed} ago`;
}

/** This computer's own token cannot be revoked from here: it would lock the app out. */
export function canRevoke(device: ListedDevice): boolean {
  return !device.is_local && !device.this_device;
}

/** Seconds until the code expires; zero once it has. */
export function secondsLeft(expiresAt: string, now: Date): number {
  return Math.max(0, Math.ceil((new Date(expiresAt).getTime() - now.getTime()) / 1000));
}

/** "Expires in 4:59", or "Expired". */
export function expiryText(expiresAt: string, now: Date): string {
  const seconds = secondsLeft(expiresAt, now);
  if (seconds === 0) return "Expired";
  return `Expires in ${String(Math.floor(seconds / 60))}:${String(seconds % 60).padStart(2, "0")}`;
}
