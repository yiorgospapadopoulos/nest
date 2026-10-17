import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { StorageUsage } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { repo, storageUsage, storedAttachment } from "../../test/fixtures.ts";
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
      "Pixies",
      "Accounts",
      "Extensions",
      "Devices",
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

describe("storage", () => {
  it("shows the space used and saves when idle chats are archived", async () => {
    const api = fakeApi();
    const { user } = await openGeneral(api);

    expect(await screen.findByText("1.4 GB")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "chats 820 MB, attachments 540 MB, artifacts 40 MB" }),
    ).toBeInTheDocument();
    const archive = screen.getByLabelText("Archive chats idle for");
    expect(
      within(archive)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Never", "7 days", "30 days", "90 days"]);
    await user.selectOptions(archive, "30");

    expect(api.saveStorageSettings).toHaveBeenCalledWith({ archive_after_days: 30 });
    expect(archive).toHaveValue("30");
  });

  it.each<[Partial<StorageUsage>, string]>([
    [{ total_bytes: 512 }, "512 bytes"],
    [{ total_bytes: 4_200 }, "4.2 KB"],
    [{ total_bytes: 12_000_000 }, "12 MB"],
    [{ total_bytes: 3_000_000_000_000 }, "3 TB"],
    [{ total_bytes: 0, chats_bytes: 0, attachments_bytes: 0, artifacts_bytes: 0 }, "0 bytes"],
  ])("writes %o as %s", async (usage, text) => {
    const api = fakeApi();
    api.storage.mockResolvedValue(storageUsage(usage));
    await openGeneral(api);

    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("keeps a saved archive age the list does not offer, and puts back a refused one", async () => {
    const api = fakeApi();
    api.storageSettings.mockResolvedValue({ archive_after_days: 14 });
    api.saveStorageSettings.mockRejectedValueOnce(new ApiError(409, "settings.toml broke"));
    const { user } = await openGeneral(api);
    const archive = await screen.findByLabelText("Archive chats idle for");

    expect(within(archive).getAllByRole("option").at(-1)).toHaveTextContent("14 days");
    await user.selectOptions(archive, "null");

    expect(await screen.findByText("settings.toml broke")).toBeInTheDocument();
    expect(archive).toHaveValue("14");
  });

  it("waits for the storage settings", async () => {
    const api = fakeApi();
    api.storageSettings.mockReturnValue(new Promise(() => undefined));
    await openGeneral(api);

    expect(screen.getByRole("region", { name: "Storage" })).toHaveTextContent("Loading...");
  });

  it("waits for the space used and the version", async () => {
    const slow = fakeApi();
    slow.storage.mockReturnValue(new Promise(() => undefined));
    slow.health.mockReturnValue(new Promise(() => undefined));
    await openGeneral(slow);
    expect(screen.getAllByText("...")).toHaveLength(2);
  });

  it("shows no version when the Mac does not say, and ignores an unknown choice", async () => {
    const api = fakeApi();
    api.health.mockRejectedValue(new ApiError(502, "Bad gateway"));
    await openGeneral(api);

    await screen.findByText("1.4 GB");
    expect(screen.getByText("...")).toBeInTheDocument();
    expect(screen.queryByText("Bad gateway")).not.toBeInTheDocument();
    // A value no option has (the list changed under the user) is not saved.
    fireEvent.change(screen.getByLabelText("Archive chats idle for"), {
      target: { value: "nope" },
    });
    expect(api.saveStorageSettings).not.toHaveBeenCalled();
  });

  it("rebuilds the search index", async () => {
    const api = fakeApi();
    const { user } = await openGeneral(api);

    await user.click(await screen.findByRole("button", { name: "Rebuild" }));

    expect(api.rebuildSearch).toHaveBeenCalled();
    expect(await screen.findByText("Rebuilding the search index")).toBeInTheDocument();
  });

  it("says so when rebuilding is refused", async () => {
    const api = fakeApi();
    api.rebuildSearch.mockRejectedValue(new ApiError(500, "index broke"));
    const { user } = await openGeneral(api);

    await user.click(await screen.findByRole("button", { name: "Rebuild" }));

    expect(await screen.findByText("index broke")).toBeInTheDocument();
  });

  it("lists the large attachments and deletes one only after confirming", async () => {
    const api = fakeApi();
    api.largeAttachments.mockResolvedValue([
      storedAttachment(),
      storedAttachment({ id: "a2", name: "log.txt", bytes: 900, session_title: null }),
    ]);
    const { user } = await openGeneral(api);

    await user.click(await screen.findByRole("button", { name: "Review large attachments" }));
    const sheet = await screen.findByRole("dialog", { name: "Large attachments" });
    expect(await within(sheet).findByText("4.2 MB, Validate contact form")).toBeInTheDocument();
    expect(within(sheet).getByText("900 bytes")).toBeInTheDocument();
    expect(api.largeAttachments).toHaveBeenCalledWith(20);

    await user.click(within(sheet).getByRole("button", { name: "Delete screenshot.png" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(api.deleteAttachment).not.toHaveBeenCalled();
    await user.click(within(sheet).getByRole("button", { name: "Delete screenshot.png" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Delete screenshot.png?" });
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));

    expect(api.deleteAttachment).toHaveBeenCalledWith("a1");
    expect(await screen.findByText("Deleted screenshot.png")).toBeInTheDocument();
    await waitFor(() => {
      expect(within(sheet).queryByText("screenshot.png")).not.toBeInTheDocument();
    });
    await user.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps an attachment the Mac would not delete, and says when there are none", async () => {
    const api = fakeApi();
    api.largeAttachments
      .mockResolvedValueOnce([storedAttachment()])
      .mockRejectedValueOnce(new ApiError(500, "cannot list"));
    api.deleteAttachment.mockRejectedValue(new ApiError(404, "unknown attachment"));
    const { user } = await openGeneral(api);

    await user.click(await screen.findByRole("button", { name: "Review large attachments" }));
    await user.click(await screen.findByRole("button", { name: "Delete screenshot.png" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );
    expect(await screen.findByText("unknown attachment")).toBeInTheDocument();
    expect(screen.getByText("screenshot.png")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Done" }));

    await user.click(screen.getByRole("button", { name: "Review large attachments" }));
    expect(await screen.findByText("No attachments")).toBeInTheDocument();
  });

  it("ignores a list that arrives after the sheet closed", async () => {
    const api = fakeApi();
    let finish: (value: never[]) => void = () => undefined;
    api.largeAttachments.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { user } = await openGeneral(api);

    await user.click(await screen.findByRole("button", { name: "Review large attachments" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Loading...");
    await user.click(screen.getByRole("button", { name: "Done" }));
    finish([]);

    await waitFor(() => {
      expect(screen.queryByText("No attachments")).not.toBeInTheDocument();
    });
  });

  it("ignores the space and version that arrive after leaving", async () => {
    const api = fakeApi();
    let usage: (value: StorageUsage) => void = () => undefined;
    let health: (value: { status: "ok"; version: string }) => void = () => undefined;
    api.storage.mockReturnValue(
      new Promise((resolve) => {
        usage = resolve;
      }),
    );
    api.health.mockReturnValue(
      new Promise((resolve) => {
        health = resolve;
      }),
    );
    const { user } = await openGeneral(api);
    await user.click(screen.getByRole("button", { name: "Back to Settings" }));

    usage(storageUsage());
    health({ status: "ok", version: "9.9.9" });
    await waitFor(() => {
      expect(screen.queryByText("9.9.9")).not.toBeInTheDocument();
    });
  });
});
