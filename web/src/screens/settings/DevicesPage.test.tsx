import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { ListedDevice } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { device } from "../../test/fixtures.ts";
import { openSettings } from "../../test/settings.ts";

describe("devices", () => {
  it("lists the paired devices with Revoke for all but the Mac and this device", async () => {
    const api = fakeApi();
    api.devices.mockResolvedValue([
      device({ id: "mac", name: "MacBook Air", is_local: true }),
      device({ id: "me", name: "My iPhone", this_device: true }),
      device({ id: "ipad", name: "iPad" }),
      device({ id: "old", name: "Old phone", revoked_at: "2026-10-01T10:00:00Z" }),
    ]);
    await openSettings("Devices", { api });

    expect(await screen.findByText("MacBook Air")).toBeInTheDocument();
    expect(screen.getByText("This Mac")).toBeInTheDocument();
    expect(screen.getByText("This device")).toBeInTheDocument();
    expect(screen.queryByText("Old phone")).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /^Revoke/ }).map((b) => b.getAttribute("aria-label")),
    ).toEqual(["Revoke iPad"]);
  });

  it("labels the daemon's own device with its machine's name (B105)", async () => {
    const api = fakeApi();
    api.health.mockResolvedValue({ status: "ok", version: "0.1.0", machine: "Mac mini" });
    api.devices.mockResolvedValue([device({ id: "mac", name: "This Mac", is_local: true })]);
    await openSettings("Devices", { api });

    const row = (await screen.findByText("Mac mini")).closest(".srow");
    expect(row).toHaveTextContent("This Mac");
    expect(row).toHaveTextContent("Mac mini");
    expect(screen.getAllByText("This Mac")).toHaveLength(1);
  });

  it("revokes a device after a confirmation", async () => {
    const api = fakeApi();
    const { user } = await openSettings("Devices", { api });

    await user.click(await screen.findByRole("button", { name: "Revoke iPhone" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(api.revokeDevice).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Revoke iPhone" }));
    const confirm = screen.getByRole("alertdialog", { name: "Revoke iPhone?" });
    await user.click(within(confirm).getByRole("button", { name: "Revoke" }));

    expect(api.revokeDevice).toHaveBeenCalledWith("d1");
    expect(await screen.findByText("Revoked iPhone")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Revoke iPhone" })).not.toBeInTheDocument();
    });
  });

  it("keeps a device the Mac would not revoke", async () => {
    const api = fakeApi();
    api.revokeDevice.mockRejectedValue(new ApiError(404, "unknown device"));
    const { user } = await openSettings("Devices", { api });

    await user.click(await screen.findByRole("button", { name: "Revoke iPhone" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Revoke" }),
    );

    expect(await screen.findByText("unknown device")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revoke iPhone" })).toBeInTheDocument();
  });

  it("makes a pairing code for another device", async () => {
    const api = fakeApi();
    const { user } = await openSettings("Devices", { api });

    await user.click(screen.getByRole("button", { name: "Pair a device" }));

    const sheet = await screen.findByRole("dialog", { name: "Pair a device" });
    expect(within(sheet).getByLabelText("Pairing code")).toHaveTextContent("ABCD2345");
    expect(within(sheet).getByText(/^Until \d\d:\d\d$/)).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows nothing new when no code can be made, and waits for the list", async () => {
    const api = fakeApi();
    api.pairingCode.mockRejectedValue(new ApiError(500, "no code"));
    api.devices.mockReturnValue(new Promise<ListedDevice[]>(() => undefined));
    const { user } = await openSettings("Devices", { api });

    expect(screen.getByText("Loading...")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pair a device" }));
    expect(await screen.findByText("no code")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows no devices when the list cannot load, and ignores one that arrives late", async () => {
    const api = fakeApi();
    api.devices.mockRejectedValueOnce(new ApiError(500, "no list"));
    const first = await openSettings("Devices", { api });
    expect(await screen.findByText("no list")).toBeInTheDocument();
    expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
    first.unmount();

    let finish: (value: ListedDevice[]) => void = () => undefined;
    api.devices.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { user } = await openSettings("Devices", { api });
    await user.click(screen.getByRole("button", { name: "Back to Settings" }));
    finish([device({ name: "Late phone" })]);
    await waitFor(() => {
      expect(screen.queryByText("Late phone")).not.toBeInTheDocument();
    });
  });
});
