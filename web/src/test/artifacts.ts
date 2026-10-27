import { screen, waitFor, within } from "@testing-library/react";
import { expect } from "vitest";
import type { Artifact, JsonObject, NestEvent, Session } from "../api/types.ts";
import { fakeApi, type FakeApi } from "./fakeApi.ts";
import { artifact, detail, repo, session } from "./fixtures.ts";
import { activityTime } from "../format.ts";
import { memoryStorage, renderApp } from "./render.tsx";

export const plan = artifact({
  id: "a1",
  title: "Rollout plan",
  latest_version: 3,
  version_count: 3,
  updated_at: "2026-10-06T09:00:00Z",
});
export const report = artifact({
  id: "a2",
  title: "Usage report",
  kind: "html",
  seen: true,
  updated_at: "2026-10-06T09:30:00Z",
});

interface Setup {
  api?: FakeApi;
  chat?: Session;
  events?: NestEvent[];
  storage?: Storage;
}

/** The app with a chat open, and the API answering for artifacts. */
export async function openChat({
  api = fakeApi(),
  chat = session(),
  events = [],
  storage = memoryStorage(),
}: Setup = {}) {
  api.repos.mockResolvedValue([repo("todo-ui")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.sessionEvents.mockResolvedValue(events);
  // Opened from its address: the tab bar sits under the chat, so wait for the socket instead.
  window.history.replaceState(null, "", `/chat/${encodeURIComponent(chat.id)}`);
  const rendered = await renderApp({ api, storage, ready: false });
  await screen.findByRole("region", { name: chat.title });
  const { sockets } = rendered;
  await waitFor(() => {
    expect(sockets.sockets).not.toHaveLength(0);
  });
  return { ...rendered, reconnect: rendered.sockets.reconnect };
}

/** The reader's sandboxed frame. */
export function frameIn(sheet: HTMLElement): HTMLIFrameElement {
  const frame = sheet.querySelector("iframe");
  if (frame === null) throw new Error("no frame");
  return frame;
}

/** Waits until the reader's frame shows a page holding the text. */
export async function showing(sheet: HTMLElement, text: string) {
  await waitFor(() => {
    expect(frameIn(sheet).getAttribute("srcdoc")).toContain(text);
  });
}

/** The history, opened from the chat's header. */
export async function openHistory(rendered: Awaited<ReturnType<typeof openChat>>) {
  await rendered.user.click(screen.getByRole("button", { name: /^Artifacts/ }));
  return screen.findByRole("dialog", { name: "Artifacts" });
}

export const rows = () =>
  within(screen.getByRole("list", { name: "Artifacts" }))
    .getAllByRole("button")
    .map((row) => row.textContent);

export const saved = (found: Artifact, unseen: number): Partial<NestEvent> & { type: string } => ({
  id: 50,
  type: "artifact.saved",
  session_id: null,
  payload: {
    artifact: found as unknown as JsonObject,
    action: "updated",
    version: found.latest_version,
    unseen,
  },
});

export const at = (iso: string) => activityTime(iso, new Date());
