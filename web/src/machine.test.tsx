import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "./api/client.ts";
import { MACHINE_KEY } from "./store/devicePrefs.ts";
import { fakeApi } from "./test/fakeApi.ts";
import { memoryStorage, renderApp } from "./test/render.tsx";
import { openSettings } from "./test/settings.ts";

// The PWA belongs to the daemon that serves it, and names that daemon's machine (B105).

function onMachine(machine: string) {
  const api = fakeApi();
  api.health.mockResolvedValue({ status: "ok", version: "0.1.0", machine });
  return api;
}

function savedMachine(machine: string): Storage {
  const storage = memoryStorage();
  storage.setItem(MACHINE_KEY, machine);
  return storage;
}

describe("the daemon's machine", () => {
  it("names the machine to pair with, and shows its address", async () => {
    const api = onMachine("Mac mini");
    api.repos.mockRejectedValueOnce(new ApiError(401, "not authenticated"));
    await renderApp({ api, ready: false });

    const form = await screen.findByRole("form", { name: "Pair with Mac mini" });
    expect(form).toHaveTextContent(
      "On Mac mini, run nestd pair, or open Settings > Devices in a Nest app connected to it, " +
        "then enter the code it shows.",
    );
    expect(within(form).getByText("mac.ts.net")).toHaveClass("mono");
  });

  it("falls back to your Mac on pairing while the name is unknown", async () => {
    const api = fakeApi();
    api.repos.mockRejectedValueOnce(new ApiError(401, "not authenticated"));
    await renderApp({ api, ready: false });

    const form = await screen.findByRole("form", { name: "Pair this iPhone" });
    expect(form).toHaveTextContent("On your Mac, run nestd pair, or open Settings > Devices");
  });

  it("remembers the name, so the offline notice can name a machine it cannot reach", async () => {
    const storage = memoryStorage();
    const { unmount } = await renderApp({ api: onMachine("Mac mini"), storage });
    await waitFor(() => {
      expect(storage.getItem(MACHINE_KEY)).toBe("Mac mini");
    });
    unmount();

    const api = fakeApi();
    api.health.mockRejectedValue(new TypeError("Failed to fetch"));
    api.repos.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const { user } = await renderApp({ api, storage, ready: false });

    const notice = await screen.findByRole("region", { name: "Can't reach Mac mini" });
    expect(notice).toHaveTextContent(
      "Check that Mac mini is awake, Nest is running there and tailscale serve is on.",
    );
    await user.click(within(notice).getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Nothing needs you.")).toBeInTheDocument();
    // Retrying asks for the name again.
    expect(api.health).toHaveBeenCalledTimes(2);
  });

  it("keeps today's offline wording while the name is unknown", async () => {
    const api = fakeApi();
    api.repos.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await renderApp({ api, ready: false });

    const notice = await screen.findByRole("region", { name: "Can't reach your Mac" });
    expect(notice).toHaveTextContent("Check that the Mac is awake and Nest is running.");
  });

  it("learns a new name and keeps the saved one when the daemon has none", async () => {
    const storage = savedMachine("Old name");
    await renderApp({ api: onMachine("Studio"), storage });
    await waitFor(() => {
      expect(storage.getItem(MACHINE_KEY)).toBe("Studio");
    });

    const older = savedMachine("Mac mini");
    const { sockets } = await renderApp({ api: fakeApi(), storage: older });
    expect(older.getItem(MACHINE_KEY)).toBe("Mac mini");
    act(() => {
      sockets.last().drop(4403);
    });
    expect(
      await screen.findByRole("region", { name: "This address is not allowed" }),
    ).toHaveTextContent("Add it to server.allowed_origins in the daemon settings on Mac mini.");
  });

  it("works without storage, naming the machine for this visit only", async () => {
    const broken = memoryStorage();
    broken.getItem = () => {
      throw new Error("blocked");
    };
    broken.setItem = () => {
      throw new Error("blocked");
    };
    const { user } = await renderApp({ api: onMachine("Mac mini"), storage: broken });

    await user.click(screen.getByRole("tab", { name: "Settings" }));

    expect(await screen.findByRole("region", { name: "Connected to" })).toHaveTextContent(
      "Mac mini",
    );
  });

  it("shows which machine Settings is connected to, and how to add another", async () => {
    await openSettings(null, { api: onMachine("Mac mini") });

    const card = await screen.findByRole("region", { name: "Connected to" });
    await waitFor(() => {
      expect(within(card).getByText("Mac mini")).toBeInTheDocument();
    });
    expect(within(card).getByText("mac.ts.net")).toHaveClass("mono");
    expect(card).toHaveTextContent(
      "This app is Mac mini's. For another machine, open its address in Safari and add it to " +
        "the Home Screen: each one is its own app with its own pairing.",
    );
    // Above the list of pages.
    const pages = screen.getByRole("navigation", { name: "Settings" });
    expect(card.compareDocumentPosition(pages) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("calls an unknown machine your Mac in Settings", async () => {
    await openSettings(null);

    const card = await screen.findByRole("region", { name: "Connected to" });
    expect(card).toHaveTextContent("Your Mac");
    expect(card).toHaveTextContent("This app is your Mac's.");
  });
});
