import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { pixie } from "../../test/fixtures.ts";
import { openPixie } from "../../test/pixies.ts";

async function openSoul(api = fakeApi()) {
  const rendered = await openPixie(api, pixie(), "Details");
  await rendered.user.click(screen.getByRole("button", { name: /^Soul/ }));
  return { ...rendered, page: screen.getByRole("dialog", { name: "Soul" }) };
}

const stale = (text: string, hash: string) =>
  new ApiError(409, "soul changed since it was read", "stale_file", {
    detail: "soul changed since it was read",
    code: "stale_file",
    text,
    hash,
  });

describe("Pixie file page", () => {
  it("shows the file and saves it on the hash it read", async () => {
    const api = fakeApi();
    api.pixieFile.mockImplementation((_id, name) =>
      Promise.resolve(name === "soul" ? { text: "Be kind.", hash: "h1" } : { text: "", hash: "m" }),
    );
    const { user, page } = await openSoul(api);

    const field = await within(page).findByDisplayValue("Be kind.");
    expect(api.pixieFile).toHaveBeenCalledWith("p1", "soul");
    await user.type(field, " Be brief.");
    await user.click(within(page).getByRole("button", { name: "Save" }));

    expect(api.savePixieFile).toHaveBeenCalledWith("p1", "soul", "Be kind. Be brief.", "h1");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Soul" })).not.toBeInTheDocument();
    });
  });

  it("asks what to do when the file changed meanwhile", async () => {
    const api = fakeApi();
    api.pixieFile.mockImplementation((_id, name) =>
      Promise.resolve(name === "soul" ? { text: "Old", hash: "h1" } : { text: "", hash: "m" }),
    );
    api.savePixieFile
      .mockRejectedValueOnce(stale("Theirs", "h2"))
      .mockRejectedValueOnce(stale("Theirs again", "h3"));
    const { user, page } = await openSoul(api);

    const field = await within(page).findByDisplayValue("Old");
    await user.clear(field);
    await user.type(field, "Mine");
    await user.click(within(page).getByRole("button", { name: "Save" }));
    expect(await within(page).findByText("Changed meanwhile")).toBeInTheDocument();

    await user.click(within(page).getByRole("button", { name: "Keep mine" }));
    expect(api.savePixieFile).toHaveBeenLastCalledWith("p1", "soul", "Mine", "h2");
    expect(await within(page).findByText("Changed meanwhile")).toBeInTheDocument();

    await user.click(within(page).getByRole("button", { name: "Reload" }));
    expect(within(page).getByRole("textbox", { name: "Soul" })).toHaveValue("Theirs again");
    expect(within(page).queryByText("Changed meanwhile")).not.toBeInTheDocument();
    await user.click(within(page).getByRole("button", { name: "Save" }));
    expect(api.savePixieFile).toHaveBeenLastCalledWith("p1", "soul", "Theirs again", "h3");
  });

  it("keeps the page open when saving fails otherwise", async () => {
    const api = fakeApi();
    api.savePixieFile.mockRejectedValueOnce(new ApiError(422, "Too long", null));
    const { user, page } = await openSoul(api);

    await user.type(within(page).getByRole("textbox", { name: "Soul" }), "x");
    await user.click(within(page).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Too long")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Soul" })).toBeInTheDocument();
  });

  it("starts empty for a file that does not exist yet", async () => {
    const api = fakeApi();
    api.pixieFile.mockRejectedValue(new ApiError(404, "soul does not exist", null));
    const { user, page } = await openSoul(api);

    const field = within(page).getByRole("textbox", { name: "Soul" });
    await waitFor(() => {
      expect(field).toBeEnabled();
    });
    await user.type(field, "New");
    await user.click(within(page).getByRole("button", { name: "Save" }));
    expect(api.savePixieFile).toHaveBeenCalledWith("p1", "soul", "New", null);
  });

  it("closes when the file cannot be read", async () => {
    const api = fakeApi();
    const { user } = await openPixie(api, pixie(), "Details");
    api.pixieFile.mockRejectedValue(new Error("Mac asleep"));
    await user.click(screen.getByRole("button", { name: /^Soul/ }));

    expect(await screen.findByText("Mac asleep")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Soul" })).not.toBeInTheDocument();
    });
  });
});
