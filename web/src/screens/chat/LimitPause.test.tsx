import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { LimitPause, QueuedMessage, Session } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { detail, event, queuedMessage, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

// The clock when the chat opens: two minutes after the pause, an hour before the reset.
const OPENED = Date.parse("2026-10-06T12:00:00Z");
const PAUSE: LimitPause = {
  window: "five_hour",
  resets_at: "2026-10-06T13:12:00Z",
  resume_at: "2026-10-06T13:12:30Z",
  since: "2026-10-06T11:58:00Z",
};

afterEach(() => {
  vi.useRealTimers();
});

const paused = (pause: Partial<LimitPause> = {}) =>
  session({ limit_pause: { ...PAUSE, ...pause } });

async function openChat(chat: Session, queued: QueuedMessage[] = []) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail({ ...chat, queued }));
  api.sessionEvents.mockResolvedValue([]);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  // Only the clock and the ticker: testing-library polls its waits with setInterval too.
  vi.useFakeTimers({ now: OPENED, toFake: ["Date", "setInterval", "clearInterval"] });
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  return rendered;
}

const bar = () => screen.getByRole("group", { name: "Paused at the usage limit" });
const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

describe("a chat paused at a usage limit (B78)", () => {
  it("says which limit, when it resets and counts down to going on", async () => {
    await openChat(paused());

    expect(within(bar()).getByText("Paused at the 5-hour usage limit")).toBeInTheDocument();
    expect(
      within(bar()).getByText(`Resets ${clock(PAUSE.resets_at ?? "")} · goes on in 1 h 13 min`),
    ).toBeInTheDocument();
    expect(within(bar()).getByText("Then it continues where it left off.")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime((72 * 60 + 15) * 1000);
    });
    expect(within(bar()).getByText(/goes on in 15 s$/)).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    expect(within(bar()).getByText(/goes on any moment now$/)).toBeInTheDocument();
    // The status in the header reads paused, not failed.
    expect(screen.getByRole("img", { name: "Paused" })).toHaveClass("s-int");
  });

  it("reads paused in the project's chat list", async () => {
    const { user } = await openChat(paused());
    await user.click(screen.getByRole("button", { name: "Back to cv-page" }));

    expect(screen.getByRole("button", { name: /^Validate contact form, Paused/ })).toBeVisible();
  });

  it("says a retry goes on when the reset time is unknown", async () => {
    await openChat(paused({ window: null, resets_at: null, resume_at: "2026-10-06T12:28:00Z" }));

    expect(within(bar()).getByText("Paused at the usage limit")).toBeInTheDocument();
    expect(
      within(bar()).getByText("Reset time unknown · tries again in 28 min"),
    ).toBeInTheDocument();
  });

  it.each([
    ["seven_day", "weekly"],
    ["seven_day_opus", "weekly Opus"],
    ["seven_day_sonnet", "weekly Sonnet"],
    ["overage", "extra usage"],
    ["a_later_window", "usage"],
  ])("names the %s limit %s", async (window, words) => {
    await openChat(paused({ window: window as LimitPause["window"] }));

    expect(within(bar()).getByText(`Paused at the ${words} limit`)).toBeInTheDocument();
  });

  it("says the queued messages send then", async () => {
    await openChat(paused(), [
      queuedMessage({ id: "read", sent: true }),
      queuedMessage({ id: "m1" }),
      queuedMessage({ id: "m2" }),
    ]);
    expect(within(bar()).getByText("Your 2 queued messages send then.")).toBeInTheDocument();
  });

  it("says the one queued message sends then", async () => {
    await openChat(paused(), [queuedMessage()]);
    expect(within(bar()).getByText("Your queued message sends then.")).toBeInTheDocument();
  });

  it("resumes now, and leaves once the pause ends", async () => {
    const { user, api, push } = await openChat(paused());
    let finish: (value: Session) => void = () => undefined;
    api.resumeLimit.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );

    const resume = within(bar()).getByRole("button", { name: "Resume now" });
    await user.click(resume);
    expect(resume).toBeDisabled();
    expect(api.resumeLimit).toHaveBeenCalledWith("s1");
    await act(async () => {
      finish(session({ state: "running" }));
      await Promise.resolve();
    });

    expect(
      screen.queryByRole("group", { name: "Paused at the usage limit" }),
    ).not.toBeInTheDocument();
    push(event({ id: 10, type: "session.updated", payload: { session: paused() as never } }));
    expect(bar()).toBeInTheDocument();
    push(event({ id: 11, type: "session.updated", payload: { session: session() as never } }));
    expect(
      screen.queryByRole("group", { name: "Paused at the usage limit" }),
    ).not.toBeInTheDocument();
  });

  it("shows why Resume now failed and can try again", async () => {
    const { user, api } = await openChat(paused());
    api.resumeLimit.mockRejectedValueOnce(
      new ApiError(409, "Claude Code has this chat open", "open_in_claude_code"),
    );

    await user.click(within(bar()).getByRole("button", { name: "Resume now" }));

    expect(await screen.findByText("Claude Code has this chat open")).toBeInTheDocument();
    expect(within(bar()).getByRole("button", { name: "Resume now" })).toBeEnabled();
  });

  it("fetches the chat again when its pause already ended", async () => {
    const { user, api } = await openChat(paused());
    api.resumeLimit.mockRejectedValueOnce(new ApiError(409, "Not paused", "not_paused"));
    api.session.mockResolvedValue(detail({ ...session(), queued: [] }));

    await user.click(within(bar()).getByRole("button", { name: "Resume now" }));

    await waitFor(() => {
      expect(
        screen.queryByRole("group", { name: "Paused at the usage limit" }),
      ).not.toBeInTheDocument();
    });
    expect(screen.queryByText("Not paused")).not.toBeInTheDocument();
  });

  it("stops ticking once it leaves", async () => {
    const { user } = await openChat(paused());
    expect(vi.getTimerCount()).toBe(1);

    await user.click(screen.getByRole("button", { name: "Back to cv-page" }));

    expect(vi.getTimerCount()).toBe(0);
  });
});
