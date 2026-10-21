import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { JsonObject } from "../../api/types.ts";
import * as build from "../../transcript/build.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { detail, event, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

// Counts how often the transcript is built, keeping what it builds.
vi.mock("../../transcript/build.ts", async (original) => {
  const actual = await original<typeof build>();
  return { ...actual, buildTranscript: vi.fn(actual.buildTranscript) };
});

const START = "2026-10-06T10:00:00Z";
const at = (id: number, type: string, payload: JsonObject) =>
  event({ id, type, payload, ts: START });

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", { configurable: true, value: state });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

async function openWorkingChat() {
  const chat = session({ state: "running" });
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.sessionEvents.mockResolvedValue([
    at(1, "session.user_message", { text: "Fix it" }),
    at(2, "session.state", { state: "running", error: null, turn_start: true }),
  ]);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  vi.useFakeTimers({
    now: Date.parse(START) + 12_000,
    toFake: ["Date", "setInterval", "clearInterval"],
  });
  await rendered.user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));
  await screen.findByText("Working... 12s");
  return rendered;
}

afterEach(() => {
  vi.useRealTimers();
  setVisibility("visible");
});

describe("rendering cost", () => {
  it("ticks the working timer without building the transcript again", async () => {
    await openWorkingChat();
    const built = vi.mocked(build.buildTranscript).mock.calls.length;

    act(() => {
      vi.advanceTimersByTime(5_000);
    });

    expect(screen.getByText("Working... 17s")).toBeInTheDocument();
    expect(vi.mocked(build.buildTranscript).mock.calls.length).toBe(built);
  });

  it("stops ticking while the app is hidden and catches up when it shows again", async () => {
    await openWorkingChat();

    setVisibility("hidden");
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByText("Working... 12s")).toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(0);
    setVisibility("visible");

    expect(screen.getByText("Working... 1m 12s")).toBeInTheDocument();
  });

  it("pauses continuous animations while the app is hidden", async () => {
    await renderApp();

    setVisibility("hidden");
    expect(document.documentElement).toHaveAttribute("data-hidden");
    setVisibility("visible");
    expect(document.documentElement).not.toHaveAttribute("data-hidden");
  });
});
