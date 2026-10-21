import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { modelList, pixie, pixieDefaults } from "../../test/fixtures.ts";
import { openSettings } from "../../test/settings.ts";

const openPixies = (api = fakeApi()) => openSettings("Pixies", { api });
const section = (name: string) => screen.getByRole("region", { name });
const options = (label: string) =>
  within(screen.getByLabelText(label))
    .getAllByRole("option")
    .map((o) => o.textContent);

describe("pixie list", () => {
  it("lists the pixies with their autonomy and opens one", async () => {
    const api = fakeApi();
    api.pixies.mockResolvedValue([
      pixie({ id: "p1", name: "Tester" }),
      pixie({ id: "p2", name: "Coordinator", autonomy: "start", position: 1 }),
    ]);
    const { user } = await openPixies(api);

    const list = await screen.findByRole("region", { name: "Your pixies" });
    expect(within(list).getByText("Observe")).toBeInTheDocument();
    expect(within(list).getByText("Start")).toBeInTheDocument();
    expect(within(list).queryByRole("switch", { name: "Show hidden pixies" })).toBeNull();

    await user.click(within(list).getByRole("button", { name: "Open Coordinator" }));
    expect(await screen.findByRole("region", { name: "Coordinator" })).toBeInTheDocument();
  });

  it("shows hidden pixies on request", async () => {
    const api = fakeApi();
    api.pixies.mockResolvedValue([pixie(), pixie({ id: "p2", name: "Ghost", hidden: true })]);
    const { user } = await openPixies(api);

    expect(await screen.findByText("Tester")).toBeInTheDocument();
    expect(screen.queryByText("Ghost")).not.toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: "Show hidden pixies" }));
    expect(screen.getByText("Ghost")).toBeInTheDocument();
  });

  it("creates a pixie for every project and opens its details", async () => {
    const api = fakeApi();
    api.createPixie.mockResolvedValue(pixie({ id: "p9", name: "New pixie" }));
    const { user } = await openPixies(api);

    await user.click(await screen.findByRole("button", { name: "New pixie" }));

    expect(api.createPixie).toHaveBeenCalledWith({ name: "New pixie" });
    expect(await screen.findByRole("region", { name: "New pixie" })).toBeInTheDocument();
  });

  it("stays put when the pixie cannot be created", async () => {
    const api = fakeApi();
    api.createPixie.mockRejectedValue(new ApiError(500, "no pixie"));
    const { user } = await openPixies(api);

    await user.click(await screen.findByRole("button", { name: "New pixie" }));

    expect(await screen.findByText("no pixie")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Pixies" })).toBeInTheDocument();
  });
});

describe("new pixie defaults", () => {
  it("shows and saves what new pixies start with", async () => {
    const api = fakeApi();
    api.models.mockResolvedValue(modelList({ default_model: "haiku" }));
    const { user } = await openPixies(api);
    const start = await screen.findByRole("region", { name: "New pixies start with" });

    // Claude's real models (B94): no "Same as Agents"; none reads as Claude's default model.
    await waitFor(() => {
      expect(options("Model")).toEqual(["Opus 5.5", "Haiku 4.5", "Opus 4.6"]);
    });
    expect(screen.getByLabelText("Model")).toHaveDisplayValue("Haiku 4.5");
    expect(options("Autonomy")).toEqual(["Observe", "Message", "Start", "Answer"]);
    expect(options("Chats running at once")).toEqual(["1", "2", "3", "5"]);
    expect(options("Chats started per day")).toEqual(["3", "5", "10", "20"]);
    // Projects and the phone alerts level are not set per pixie (B85).
    expect(screen.queryByLabelText("Projects")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Send to the phone from")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Reports" })).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Model"), "opus");
    await user.selectOptions(screen.getByLabelText("Autonomy"), "message");
    await user.click(within(start).getByRole("button", { name: "Read only" }));
    await user.selectOptions(screen.getByLabelText("Chats running at once"), "3");
    await user.selectOptions(screen.getByLabelText("Chats started per day"), "10");
    await user.click(screen.getByRole("switch", { name: "Pause all habits" }));
    await user.selectOptions(screen.getByLabelText("Skip habit runs above"), "90");

    expect(api.savePixieDefaults).toHaveBeenLastCalledWith({
      model: "opus",
      autonomy: "message",
      project_access: "read",
      max_running: 3,
      max_per_day: 10,
      habits_paused: true,
      habit_usage_percent: 90,
    });
  });

  it("keeps values the lists do not offer", async () => {
    const api = fakeApi();
    api.pixieDefaults.mockResolvedValue(
      pixieDefaults({
        model: "sonnet-x",
        max_running: 7,
        max_per_day: 50,
        habit_usage_percent: 60,
      }),
    );
    await openPixies(api);

    await waitFor(() => {
      expect(screen.getByLabelText("Model")).toHaveDisplayValue("sonnet-x");
    });
    expect(screen.getByLabelText("Chats running at once")).toHaveValue("7");
    expect(screen.getByLabelText("Chats started per day")).toHaveValue("50");
    expect(screen.getByLabelText("Skip habit runs above")).toHaveDisplayValue("60%");
  });

  it("works without the model list, and puts back a refused change", async () => {
    const api = fakeApi();
    api.models.mockRejectedValue(new ApiError(500, "no models"));
    api.savePixieDefaults.mockRejectedValueOnce(new ApiError(409, "settings.toml broke"));
    const { user } = await openPixies(api);

    await screen.findByRole("region", { name: "Habits" });
    expect(options("Model")).toEqual(["Model"]);
    await user.click(screen.getByRole("switch", { name: "Pause all habits" }));

    expect(await screen.findByText("settings.toml broke")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Pause all habits" })).not.toBeChecked();
  });

  it("waits for the Mac", async () => {
    const api = fakeApi();
    api.pixieDefaults.mockReturnValue(new Promise(() => undefined));
    await openPixies(api);

    expect(section("New pixies start with")).toHaveTextContent("Loading...");
  });
});
