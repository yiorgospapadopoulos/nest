import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { pixie } from "../../test/fixtures.ts";
import { openPixie } from "../../test/pixies.ts";

const MEMORY = "# Memory\n\n- 2026-10-01: Uses pnpm\n- 2026-10-02: Likes short PRs\n";

function withMemory(text = MEMORY) {
  const api = fakeApi();
  api.pixieFile.mockImplementation((_id, name) =>
    Promise.resolve(
      name === "memory" ? { text, hash: "m1" } : { text: "Release notes", hash: "n1" },
    ),
  );
  api.savePixieFile.mockImplementation((_id, _name, saved) =>
    Promise.resolve({ text: saved, hash: "m2" }),
  );
  return api;
}

async function openMemory(api: FakeApi) {
  const rendered = await openPixie(api, pixie(), "Details");
  await rendered.user.click(await screen.findByRole("button", { name: /^Memory/ }));
  return { ...rendered, page: screen.getByRole("dialog", { name: "Memory" }) };
}

describe("Pixie memory page", () => {
  it("lists the facts and removes one", async () => {
    const api = withMemory();
    const { user, page } = await openMemory(api);

    expect(await within(page).findByText("Uses pnpm")).toBeInTheDocument();
    expect(within(page).getByText("Likes short PRs")).toBeInTheDocument();
    expect(within(page).getByText("2026-10-02")).toBeInTheDocument();
    await user.click(within(page).getByRole("button", { name: "Remove fact: Uses pnpm" }));

    expect(api.savePixieFile).toHaveBeenCalledWith(
      "p1",
      "memory",
      "# Memory\n\n- 2026-10-02: Likes short PRs\n",
      "m1",
    );
    await waitFor(() => {
      expect(within(page).queryByText("Uses pnpm")).not.toBeInTheDocument();
    });
    // The next change names the new hash.
    await user.click(within(page).getByRole("button", { name: "Remove fact: Likes short PRs" }));
    expect(api.savePixieFile).toHaveBeenLastCalledWith("p1", "memory", "# Memory\n\n", "m2");
    expect(await within(page).findByText("No facts yet")).toBeInTheDocument();
  });

  it("adds a dated fact", async () => {
    const api = withMemory("# Memory");
    const { user, page } = await openMemory(api);

    const field = await within(page).findByRole("textbox", { name: "Add fact" });
    await user.type(field, "  {Enter}");
    expect(api.savePixieFile).not.toHaveBeenCalled();
    await user.type(field, "Prefers pnpm{Enter}");

    expect(api.savePixieFile).toHaveBeenCalledWith(
      "p1",
      "memory",
      expect.stringMatching(/^# Memory\n- \d{4}-\d{2}-\d{2}: Prefers pnpm\n$/),
      "m1",
    );
    expect(await within(page).findByText("Prefers pnpm")).toBeInTheDocument();
    expect(field).toHaveValue("");

    await user.type(field, "Short PRs");
    await user.click(within(page).getByRole("button", { name: "Add" }));
    expect(api.savePixieFile).toHaveBeenLastCalledWith(
      "p1",
      "memory",
      expect.stringMatching(/Prefers pnpm\n- \d{4}-\d{2}-\d{2}: Short PRs\n$/),
      "m2",
    );
  });

  it("takes the newer memory when it changed meanwhile", async () => {
    const api = withMemory();
    api.savePixieFile
      .mockRejectedValueOnce(
        new ApiError(409, "memory changed", "stale_file", {
          text: "- 2026-10-03: Newer fact\n",
          hash: "m9",
        }),
      )
      .mockRejectedValueOnce(new Error("Mac asleep"));
    const { user, page } = await openMemory(api);

    await user.click(await within(page).findByRole("button", { name: "Remove fact: Uses pnpm" }));
    expect(await within(page).findByText("Newer fact")).toBeInTheDocument();
    expect(screen.getByText("Memory changed meanwhile. Try again.")).toBeInTheDocument();

    await user.type(within(page).getByRole("textbox", { name: "Add fact" }), "More{Enter}");
    expect(api.savePixieFile).toHaveBeenLastCalledWith(
      "p1",
      "memory",
      expect.stringContaining("Newer fact"),
      "m9",
    );
    expect(await screen.findByText("Mac asleep")).toBeInTheDocument();
    expect(within(page).getByRole("textbox", { name: "Add fact" })).toHaveValue("More");
  });

  it("starts empty without a memory file", async () => {
    const api = withMemory();
    api.pixieFile.mockRejectedValue(new ApiError(404, "memory does not exist", null));
    const { user, page } = await openMemory(api);

    expect(await within(page).findByText("No facts yet")).toBeInTheDocument();
    await user.type(within(page).getByRole("textbox", { name: "Add fact" }), "First{Enter}");
    expect(api.savePixieFile).toHaveBeenCalledWith(
      "p1",
      "memory",
      expect.stringMatching(/^- \d{4}-\d{2}-\d{2}: First\n$/),
      null,
    );
  });

  it("shows a fact written without a date as it is", async () => {
    const { page } = await openMemory(withMemory("- Undated fact\n"));

    expect(await within(page).findByText("Undated fact")).toBeInTheDocument();
  });

  it("closes when memory cannot be read", async () => {
    const api = withMemory();
    const { user } = await openPixie(api, pixie(), "Details");
    await screen.findByRole("button", { name: /^Memory.*facts/ });
    api.pixieFile.mockRejectedValue(new Error("Mac asleep"));
    await user.click(screen.getByRole("button", { name: /^Memory/ }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Memory" })).not.toBeInTheDocument();
    });
    expect(await screen.findByText("Mac asleep")).toBeInTheDocument();
  });

  it("opens notes", async () => {
    const api = withMemory();
    api.pixieNotes.mockResolvedValue(["release", "tooling"]);
    const { user, page } = await openMemory(api);

    await user.click(await within(page).findByRole("button", { name: "release" }));
    expect(api.pixieFile).toHaveBeenCalledWith("p1", "notes/release");
    const note = screen.getByRole("dialog", { name: "release" });
    expect(await within(note).findByDisplayValue("Release notes")).toBeInTheDocument();
    await user.click(within(note).getByRole("button", { name: "Close" }));
    expect(screen.getByRole("dialog", { name: "Memory" })).toBeInTheDocument();
  });

  it("says when there are no notes, and when they cannot load", async () => {
    const api = withMemory();
    api.pixieNotes.mockRejectedValueOnce(new Error("Mac asleep"));
    const { page } = await openMemory(api);

    expect(await within(page).findByText("No notes yet")).toBeInTheDocument();
  });

  it("searches memory and notes", async () => {
    const api = withMemory();
    api.searchPixie
      .mockResolvedValueOnce([{ file: "notes/tooling.md", line: "pnpm workspaces" }])
      .mockResolvedValueOnce([]);
    const { user, page } = await openMemory(api);

    const search = within(page).getByRole("searchbox", { name: "Search memory" });
    await user.type(search, "  {Enter}");
    expect(api.searchPixie).not.toHaveBeenCalled();
    await user.clear(search);
    await user.type(search, "pnpm{Enter}");

    expect(api.searchPixie).toHaveBeenCalledWith("p1", "pnpm");
    expect(await within(page).findByText("notes/tooling.md: pnpm workspaces")).toBeInTheDocument();
    await user.clear(search);
    await user.type(search, "yarn{Enter}");
    expect(await within(page).findByText("No matches")).toBeInTheDocument();
  });

  it("goes back to the details", async () => {
    const api = withMemory();
    const { user, page } = await openMemory(api);

    await user.click(within(page).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog", { name: "Memory" })).not.toBeInTheDocument();
  });
});
