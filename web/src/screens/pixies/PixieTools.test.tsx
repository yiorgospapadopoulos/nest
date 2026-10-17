import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PixieActivity } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { detail, pixie, repo, session } from "../../test/fixtures.ts";
import { openPixie } from "../../test/pixies.ts";

const details = (api = fakeApi(), shown = pixie()) => openPixie(api, shown, "Details");

const sheet = (name: string) => screen.getByRole("dialog", { name });

function entry(overrides: Partial<PixieActivity> = {}): PixieActivity {
  return {
    id: 1,
    ts: new Date().toISOString(),
    tool: "send_message",
    session_id: "s1",
    summary: "Asked for the test results",
    ...overrides,
  };
}

describe("Pixie Nest tools in its details (B41)", () => {
  it("explains what each autonomy level lets the pixie do", async () => {
    const { user } = await details();

    await user.click(screen.getByRole("button", { name: "Autonomy: Observe" }));
    const levels = sheet("Autonomy");
    for (const [level, note] of [
      ["Observe", "Reads chats in your projects"],
      ["Message", "Also writes to them, nudges or stops them"],
      ["Start", "Also starts chats in their own worktree"],
      ["Answer", "Also answers approvals, questions and plans in chats it started"],
    ] as const) {
      expect(
        within(levels).getByRole("menuitemradio", { name: new RegExp(`^${level}`) }),
      ).toHaveTextContent(note);
    }
  });

  it("steps the limits within their ranges, saving each step", async () => {
    const api = fakeApi();
    const { user } = await details(api, pixie({ max_running: 1, max_per_day: 100 }));

    const running = screen.getByRole("group", { name: "Running chats at once" });
    expect(running).toHaveTextContent("1");
    expect(within(running).getByRole("button", { name: "Fewer" })).toBeDisabled();
    await user.click(within(running).getByRole("button", { name: "More" }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { max_running: 2 });
    await waitFor(() => {
      expect(running).toHaveTextContent("2");
    });

    const daily = screen.getByRole("group", { name: "New chats per day" });
    expect(within(daily).getByRole("button", { name: "More" })).toBeDisabled();
    await user.click(within(daily).getByRole("button", { name: "Fewer" }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { max_per_day: 99 });
  });

  it("keeps quick steps and stops at the top of the range", async () => {
    const api = fakeApi();
    const shown = pixie({ max_running: 18 });
    const { user } = await details(api, shown);
    // Each save waits until the test answers it.
    let release = () => undefined as unknown;
    api.updatePixie.mockImplementation(
      (_id, body) =>
        new Promise((resolve) => {
          release = () => {
            resolve({ ...shown, ...body });
          };
        }),
    );

    const running = screen.getByRole("group", { name: "Running chats at once" });
    const more = within(running).getByRole("button", { name: "More" });
    await user.click(more);
    await user.click(more);
    expect(running).toHaveTextContent("20");
    expect(more).toBeDisabled();
    release();
    await waitFor(() => {
      expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { max_running: 20 });
    });
    expect(running).toHaveTextContent("20");
    release();
    await waitFor(() => {
      expect(running).toHaveTextContent("20");
    });
  });

  it("shows the saved limit again when the Mac refuses a step", async () => {
    const api = fakeApi();
    const { user } = await details(api, pixie({ max_per_day: 5 }));
    api.updatePixie.mockRejectedValueOnce(new Error("Mac asleep"));

    const daily = screen.getByRole("group", { name: "New chats per day" });
    await user.click(within(daily).getByRole("button", { name: "More" }));
    expect(await screen.findByText("Mac asleep")).toBeInTheDocument();
    await waitFor(() => {
      expect(daily).toHaveTextContent("5");
    });
  });

  it("lists the activity log, newest first, and opens a chat from it", async () => {
    const api = fakeApi();
    const chat = session({ id: "s1", title: "Validate contact form" });
    api.repos.mockResolvedValue([repo("cv-page")]);
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
    api.session.mockResolvedValue(detail(chat));
    api.pixieActivity.mockResolvedValue([
      entry({ id: 2, tool: "start_session", summary: "Started a check" }),
      entry({ id: 1, tool: "nudge", session_id: "gone", summary: "Nudged an old chat" }),
      entry({ id: 0, tool: "card", session_id: null, summary: "Posted a card" }),
    ]);
    const { user } = await details(api);

    await user.click(screen.getByRole("button", { name: /^Activity/ }));
    const page = sheet("Activity");
    const rows = await within(page).findAllByRole("listitem");
    expect(api.pixieActivity).toHaveBeenCalledWith("p1");
    // Tool names read as words, as on the Mac.
    expect(rows.map((row) => row.querySelector(".pxacth b")?.textContent)).toEqual([
      "Start session",
      "Nudge",
      "Card",
    ]);
    expect(within(defined(rows[0])).getByText("Started a check")).toBeInTheDocument();
    // Unknown chats are named without a link; a call without a chat names none.
    expect(within(defined(rows[1])).getByText("A chat no longer listed")).toBeInTheDocument();
    expect(within(defined(rows[2])).queryByRole("button")).not.toBeInTheDocument();

    await user.click(within(page).getByRole("button", { name: "Validate contact form" }));
    expect(
      await screen.findByRole("region", { name: "Validate contact form" }),
    ).toBeInTheDocument();
  });

  it("says when there is no activity yet, or it cannot load, and closes", async () => {
    const api = fakeApi();
    const { user } = await details(api);

    await user.click(screen.getByRole("button", { name: /^Activity/ }));
    expect(await within(sheet("Activity")).findByText("Nothing yet")).toBeInTheDocument();
    await user.click(within(sheet("Activity")).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog", { name: "Activity" })).not.toBeInTheDocument();

    api.pixieActivity.mockRejectedValueOnce(new Error("Mac asleep"));
    await user.click(screen.getByRole("button", { name: /^Activity/ }));
    expect(
      await within(sheet("Activity")).findByText("The activity could not be loaded."),
    ).toBeInTheDocument();
  });
});
