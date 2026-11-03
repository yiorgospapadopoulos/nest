import { describe, expect, it } from "vitest";
import type { ListedDevice } from "../../../api/types.ts";
import { canRevoke, deviceDetail, deviceTitle, expiryText, shownDevices } from "./devices.ts";

const now = new Date("2026-11-03T12:00:00Z");
const device = (id: string, change: Partial<ListedDevice> = {}): ListedDevice => ({
  id,
  name: id,
  is_local: false,
  created_at: "2026-11-01T00:00:00Z",
  last_seen_at: null,
  revoked_at: null,
  this_device: false,
  ...change,
});

describe("devices", () => {
  it("lists active devices with this computer first, and never offers to revoke it", () => {
    const local = device("local", { is_local: true, this_device: true });
    const phone = device("phone", { last_seen_at: "2026-11-03T11:55:00Z" });
    const gone = device("gone", { revoked_at: "2026-11-02T00:00:00Z" });
    expect(shownDevices([phone, gone, local]).map((d) => d.id)).toEqual(["local", "phone"]);
    expect(deviceDetail(local, now)).toBe("This computer");
    expect(deviceDetail(phone, now)).toBe("Last seen 5m ago");
    expect(deviceDetail(device("new"), now)).toBe("Not seen yet");
    expect(deviceDetail(device("now", { last_seen_at: now.toISOString() }), now)).toBe(
      "Last seen now",
    );
    expect(canRevoke(local)).toBe(false);
    expect(canRevoke(device("me", { this_device: true }))).toBe(false);
    expect(canRevoke(phone)).toBe(true);
  });

  it("names this computer's device for the platform, keeping a name the user gave", () => {
    expect(deviceTitle(device("old", { name: "This Mac", is_local: true }))).toBe("This computer");
    expect(deviceTitle(device("laptop", { name: "Work laptop", is_local: true }))).toBe(
      "Work laptop",
    );
    // Another Mac paired with this daemon keeps its name.
    expect(deviceTitle(device("mac", { name: "This Mac" }))).toBe("This Mac");
  });

  it("counts the code down to Expired", () => {
    const expiry = "2026-11-03T12:05:00Z";
    const before = (seconds: number) => new Date(Date.parse(expiry) - seconds * 1000);
    expect(expiryText(expiry, before(299.5))).toBe("Expires in 5:00");
    expect(expiryText(expiry, before(61))).toBe("Expires in 1:01");
    expect(expiryText(expiry, before(9))).toBe("Expires in 0:09");
    expect(expiryText(expiry, before(0))).toBe("Expired");
  });
});
