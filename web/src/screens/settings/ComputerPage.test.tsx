// Settings > Computer use (B150): saves, and a blocked permission says so with Open on Mac.
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ComputerStatus } from "../../api/types.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { openSettings } from "../../test/settings.ts";

const BLOCKED: ComputerStatus = {
  enabled: true,
  kinds: [
    { kind: "mac", ready: true, reason: null, link: null },
    {
      kind: "android",
      ready: false,
      reason: "Android Studio is not installed.",
      link: "https://developer.android.com/studio",
    },
  ],
  accessibility: true,
  screen_recording: false,
};

function blockedApi(): FakeApi {
  const api = fakeApi();
  api.computerSettings.mockResolvedValue({
    enabled: true,
    pixies: false,
  });
  api.computerStatus.mockResolvedValue(BLOCKED);
  return api;
}

describe("Settings > Computer use (B150)", () => {
  it("saves a switch and opens a blocked permission on the Mac", async () => {
    const api = blockedApi();
    const { user } = await openSettings("computer", { api });

    const record = await screen.findByRole("switch", { name: "Screen Recording for Nest" });
    expect(record).not.toBeChecked();
    expect(screen.getByRole("switch", { name: "Accessibility for Nest Computer" })).toBeChecked();
    expect(screen.getByText("Blocked in System Settings.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open on Mac" }));
    expect(api.askComputerPermission).toHaveBeenCalledWith("screen_recording");

    await user.click(screen.getByRole("switch", { name: "Pixies may use it" }));
    expect(api.saveComputerSettings).toHaveBeenLastCalledWith({
      enabled: true,
      pixies: true,
    });
    expect(screen.getByRole("link", { name: "Get Android Studio" })).toBeInTheDocument();
  });
});
