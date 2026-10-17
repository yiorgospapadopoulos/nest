import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { StorageUsage } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { storageUsage, storedAttachment } from "../../test/fixtures.ts";
import { openSettings } from "../../test/settings.ts";

const openStorage = (api = fakeApi()) => openSettings("Storage", { api });
// The Storage ledger's lines: name, size and share.
const legend = () => [...document.querySelectorAll(".lline")].map((line) => line.textContent);

describe("storage", () => {
  it("is its own page, with the address /settings/storage", async () => {
    await openStorage();

    expect(screen.getByRole("heading", { level: 1, name: "Storage" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/settings/storage");
    expect(await screen.findByText("1.4 GB", { selector: ".ltot" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Nest" })).not.toBeInTheDocument();
  });

  it("shows the space used and saves when idle chats are archived", async () => {
    const api = fakeApi();
    const { user } = await openStorage(api);

    expect(await screen.findByText("1.4 GB", { selector: ".ltot" })).toBeInTheDocument();
    expect(screen.getByText("used by Nest")).toBeInTheDocument();
    expect(screen.queryByText("Space used")).not.toBeInTheDocument();
    expect(legend()).toEqual([
      "Chats820 MB59%",
      "Attachments540 MB39%",
      "Artifacts40 MB3%",
      "Other0 bytes0%",
    ]);
    const bar = screen.getByRole("img", {
      name: "Chats 820 MB, Attachments 540 MB, Artifacts 40 MB, Other 0 bytes",
    });
    // A part with nothing in it has no segment.
    expect([...bar.children].map((i) => i.className)).toEqual(["s-run", "s-wait", "s-rev"]);
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

  it("writes a small share as under 1%, and shares of nothing as 0%", async () => {
    const api = fakeApi();
    api.storage.mockResolvedValueOnce(
      storageUsage({
        total_bytes: 1_000_000_000,
        chats_bytes: 994_000_000,
        attachments_bytes: 1_000_000,
        artifacts_bytes: 0,
        other_bytes: 5_000_000,
      }),
    );
    await openStorage(api);

    await screen.findByText("1 GB", { selector: ".ltot" });
    expect(legend()).toEqual([
      "Chats994 MB99%",
      "Attachments1 MB<1%",
      "Artifacts0 bytes0%",
      "Other5 MB<1%",
    ]);
    const segments = [...screen.getByRole("img").children] as HTMLElement[];
    expect(segments.map((i) => i.className)).toEqual(["s-run", "s-wait", "s-oth"]);
    // Each segment grows with its size, and CSS keeps the smallest one visible.
    expect(segments.map((i) => i.style.flexGrow)).toEqual(["994000000", "1000000", "5000000"]);
  });

  it("shows 0% for every part while Nest stores nothing", async () => {
    const api = fakeApi();
    api.storage.mockResolvedValueOnce(
      storageUsage({ total_bytes: 0, chats_bytes: 0, attachments_bytes: 0, artifacts_bytes: 0 }),
    );
    await openStorage(api);

    await screen.findByText("0 bytes", { selector: ".ltot" });
    expect(legend().map((line) => line.slice(-2))).toEqual(["0%", "0%", "0%", "0%"]);
    expect(screen.getByRole("img").children).toHaveLength(0);
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
    await openStorage(api);

    expect(await screen.findByText(text, { selector: ".ltot" })).toBeInTheDocument();
  });

  it("keeps a saved archive age the list does not offer, and puts back a refused one", async () => {
    const api = fakeApi();
    api.storageSettings.mockResolvedValue({ archive_after_days: 14 });
    api.saveStorageSettings.mockRejectedValueOnce(new ApiError(409, "settings.toml broke"));
    const { user } = await openStorage(api);
    const archive = await screen.findByLabelText("Archive chats idle for");

    expect(within(archive).getAllByRole("option").at(-1)).toHaveTextContent("14 days");
    await user.selectOptions(archive, "null");

    expect(await screen.findByText("settings.toml broke")).toBeInTheDocument();
    expect(archive).toHaveValue("14");
  });

  it("waits for the storage settings", async () => {
    const api = fakeApi();
    api.storageSettings.mockReturnValue(new Promise(() => undefined));
    await openStorage(api);

    expect(await screen.findByText("Loading...")).toBeInTheDocument();
    expect(screen.queryByLabelText("Archive chats idle for")).not.toBeInTheDocument();
  });

  it("waits for the space used", async () => {
    const slow = fakeApi();
    slow.storage.mockReturnValue(new Promise(() => undefined));
    await openStorage(slow);
    expect(await screen.findByText("...")).toBeInTheDocument();
    expect(screen.getByText("Space used")).toBeInTheDocument();
  });

  it("ignores an unknown choice", async () => {
    const api = fakeApi();
    await openStorage(api);

    await screen.findByText("1.4 GB", { selector: ".ltot" });
    // A value no option has (the list changed under the user) is not saved.
    fireEvent.change(screen.getByLabelText("Archive chats idle for"), {
      target: { value: "nope" },
    });
    expect(api.saveStorageSettings).not.toHaveBeenCalled();
  });

  it("rebuilds the search index", async () => {
    const api = fakeApi();
    const { user } = await openStorage(api);

    await user.click(await screen.findByRole("button", { name: "Rebuild" }));

    expect(api.rebuildSearch).toHaveBeenCalled();
    expect(await screen.findByText("Rebuilding the search index")).toBeInTheDocument();
  });

  it("says so when rebuilding is refused", async () => {
    const api = fakeApi();
    api.rebuildSearch.mockRejectedValue(new ApiError(500, "index broke"));
    const { user } = await openStorage(api);

    await user.click(await screen.findByRole("button", { name: "Rebuild" }));

    expect(await screen.findByText("index broke")).toBeInTheDocument();
  });

  it("lists the large attachments and deletes one only after confirming", async () => {
    const api = fakeApi();
    api.largeAttachments.mockResolvedValue([
      storedAttachment(),
      storedAttachment({ id: "a2", name: "log.txt", bytes: 900, session_title: null }),
    ]);
    const { user } = await openStorage(api);

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
    const { user } = await openStorage(api);

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
    const { user } = await openStorage(api);

    await user.click(await screen.findByRole("button", { name: "Review large attachments" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Loading...");
    await user.click(screen.getByRole("button", { name: "Done" }));
    finish([]);

    await waitFor(() => {
      expect(screen.queryByText("No attachments")).not.toBeInTheDocument();
    });
  });

  it("ignores the space that arrives after leaving", async () => {
    const api = fakeApi();
    let usage: (value: StorageUsage) => void = () => undefined;
    api.storage.mockReturnValue(
      new Promise((resolve) => {
        usage = resolve;
      }),
    );
    const { user } = await openStorage(api);
    await user.click(screen.getByRole("button", { name: "Back to Settings" }));

    usage(storageUsage());
    await waitFor(() => {
      expect(screen.queryByText("used by Nest")).not.toBeInTheDocument();
    });
  });
});
