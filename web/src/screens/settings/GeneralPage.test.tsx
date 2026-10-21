import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { repo } from "../../test/fixtures.ts";
import { openSettings } from "../../test/settings.ts";

const openGeneral = (api = fakeApi()) => openSettings("General", { api });

describe("settings list", () => {
  it("lists the categories, then the projects, without keyboard shortcuts", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([repo("cv-page"), repo("narrative")]);
    await openSettings(null, { api });

    expect(
      within(screen.getByRole("navigation", { name: "Settings" }))
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual([
      "General",
      "Appearance",
      "Notifications",
      "Agents",
      "Usage",
      "Storage",
      "Pixies",
      "Accounts",
      "Devices",
      "Configuration",
    ]);
    const projects = screen.getByRole("region", { name: "Projects" });
    expect(
      within(projects)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["CPcv-page", "Nnarrative"]);
    expect(screen.queryByText("Keyboard shortcuts")).not.toBeInTheDocument();
  });

  it("leaves the Projects group out without projects, and keeps the page in the address", async () => {
    const api = fakeApi();
    api.repos.mockResolvedValue([]);
    const { user } = await openSettings(null, { api });

    expect(screen.queryByRole("region", { name: "Projects" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Devices" }));
    expect(window.location.pathname).toBe("/settings/devices");
    await user.click(screen.getByRole("button", { name: "Back to Settings" }));
    expect(window.location.pathname).toBe("/settings");
  });
});

describe("general page", () => {
  it("holds Nest itself, and leaves storage to its own page", async () => {
    await openGeneral();

    expect(await screen.findByRole("region", { name: "Nest" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Storage" })).not.toBeInTheDocument();
    expect(screen.queryByText("Archive chats idle for")).not.toBeInTheDocument();
  });

  it("waits for the version, and shows none when the Mac does not say", async () => {
    const slow = fakeApi();
    slow.health.mockReturnValue(new Promise(() => undefined));
    const first = await openGeneral(slow);
    expect(screen.getByText("...")).toBeInTheDocument();
    first.unmount();

    const api = fakeApi();
    api.health.mockRejectedValue(new ApiError(502, "Bad gateway"));
    await openGeneral(api);
    await waitFor(() => {
      expect(api.health).toHaveBeenCalled();
    });
    expect(screen.getByText("...")).toBeInTheDocument();
    expect(screen.queryByText("Bad gateway")).not.toBeInTheDocument();
  });

  it("ignores the version that arrives after leaving", async () => {
    const api = fakeApi();
    let health: (value: { status: "ok"; version: string }) => void = () => undefined;
    api.health.mockReturnValue(
      new Promise((resolve) => {
        health = resolve;
      }),
    );
    const { user } = await openGeneral(api);
    await user.click(screen.getByRole("button", { name: "Back to Settings" }));

    health({ status: "ok", version: "9.9.9" });
    await waitFor(() => {
      expect(screen.queryByText("9.9.9")).not.toBeInTheDocument();
    });
  });
});
