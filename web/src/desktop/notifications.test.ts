// Desktop notifications follow the Mac's NotificationPolicy: switched-on kinds only, never
// about the chat on screen, and named by project or pixie.
import { describe, expect, it } from "vitest";
import { memoryStorage } from "../test/render.tsx";
import { approval, pixie } from "../test/fixtures.ts";
import { ProjectState } from "./layout/project.ts";
import {
  focusedChat,
  loadPreferences,
  notificationFor,
  pillShows,
  savePreferences,
  visibleChats,
  windowActive,
  type Notice,
} from "./notifications.ts";

const size = { width: 1000, height: 600 };
const notice = (overrides: Partial<Notice> = {}): Notice => ({
  kind: "finished",
  session_id: "s1",
  repo: "todo-ui",
  title: "Fix the header",
  text: "Done: the header fits on one line.",
  ...overrides,
});
const all = loadPreferences(memoryStorage());

describe("desktop notifications", () => {
  it("say the project and the chat, and skip a chat on screen", () => {
    expect(notificationFor(notice(), all, new Set(), [])).toEqual({
      title: "todo-ui · Fix the header",
      body: "Done: the header fits on one line.",
      chat: "s1",
    });
    // A notice about no chat opens none when clicked.
    expect(notificationFor(notice({ session_id: "" }), all, new Set(), [])).not.toHaveProperty(
      "chat",
    );
    expect(notificationFor(notice(), all, new Set(["s1"]), [])).toBeNull();
  });

  it("follow this device's switches, review comments with approvals", () => {
    const storage = memoryStorage();
    savePreferences(storage, { ...all, finished: false, needs_approval: false });
    const prefs = loadPreferences(storage);
    expect(notificationFor(notice(), prefs, new Set(), [])).toBeNull();
    expect(notificationFor(notice({ kind: "review_comments" }), prefs, new Set(), [])).toBeNull();
    expect(notificationFor(notice({ kind: "question" }), prefs, new Set(), [])).not.toBeNull();
    expect(notificationFor(notice({ kind: "something_new" }), all, new Set(), [])).toBeNull();
  });

  it("name a pixie's chat by the pixie, and a report by its title", () => {
    const pixies = [pixie({ id: "p1", name: "Watcher" })];
    expect(notificationFor(notice({ repo: "pixie:p1" }), all, new Set(), pixies)?.title).toBe(
      "Watcher · Fix the header",
    );
    expect(
      notificationFor(
        notice({ kind: "pixie_report", repo: "pixie:p1", title: "The build broke" }),
        all,
        new Set(),
        pixies,
      ),
    ).toEqual({ title: "Watcher", body: "The build broke", chat: "s1" });
  });

  it("count as on screen the workspace's panes in the focused window, a maximized one alone", () => {
    const state = new ProjectState();
    state.openChat("a", size);
    state.openChat("b", size);
    expect(visibleChats(true, state, false, [])).toEqual(new Set(["a", "b"]));
    expect(visibleChats(false, state, false, [])).toEqual(new Set());
    state.layout.toggleMaximize("a");
    expect(visibleChats(true, state, false, [])).toEqual(new Set(["a"]));
    state.view = "board";
    expect(visibleChats(true, state, false, [])).toEqual(new Set());
  });

  it("count a minimised or hidden window as not looked at, though X11 calls it focused", () => {
    const window = { focused: true, pageVisible: true, minimized: false, shown: true };
    expect(windowActive(window)).toBe(true);
    // Wave 6: minimised, the window reported HIDDEN and FOCUSED at once.
    expect(windowActive({ ...window, minimized: true, shown: false })).toBe(false);
    expect(windowActive({ ...window, minimized: true })).toBe(false);
    expect(windowActive({ ...window, shown: false })).toBe(false);
    expect(windowActive({ ...window, pageVisible: false })).toBe(false);
    expect(windowActive({ ...window, focused: false })).toBe(false);
    // Without the window manager's word, the page's own state decides.
    expect(windowActive({ ...window, minimized: null, shown: null })).toBe(true);
  });

  it("see a pixie pane as its chat, and only the focused pane as seen", () => {
    const pixies = [pixie({ id: "p1", chat_session_id: "pc1" })];
    const tab = new ProjectState();
    tab.openChat("p1", size);
    expect(visibleChats(true, tab, true, pixies)).toEqual(new Set(["pc1"]));
    expect(focusedChat(true, tab, true, pixies)).toBe("pc1");
    const project = new ProjectState();
    project.openChat("a", size);
    project.openChat("b", size);
    expect(focusedChat(true, project, false, [])).toBe("b");
    expect(focusedChat(false, project, false, [])).toBeNull();
  });
});

// User, 2026-11-03: while the pill is shown, what it shows gets no notification.
describe("notifications beside the pill", () => {
  const inCall = approval({
    session_id: "s1",
    payload: { tool: "Bash", input: { command: "npm test" }, call: "tu1" },
  });
  const asking = notice({ kind: "needs_approval" });

  it("skip a pixie's approval the pill shows as needs you", () => {
    expect(pillShows(asking, true, inCall, new Set())).toBe(true);
    expect(pillShows(notice({ kind: "question" }), true, inCall, new Set())).toBe(true);
  });

  it("go out with the pill off", () => {
    expect(pillShows(asking, false, inCall, new Set())).toBe(false);
  });

  it("go out for what the pill does not show", () => {
    // A normal chat's own approval, a finished turn, a review, another chat's approval.
    const own = approval({ session_id: "s1" });
    expect(pillShows(asking, true, own, new Set())).toBe(false);
    expect(pillShows(notice({ kind: "finished" }), true, inCall, new Set())).toBe(false);
    expect(
      pillShows(notice({ kind: "review_ready" }), true, { ...inCall, kind: "review" }, new Set()),
    ).toBe(false);
    expect(pillShows(notice({ session_id: "s2" }), true, inCall, new Set())).toBe(false);
    expect(pillShows(asking, true, undefined, new Set())).toBe(false);
  });

  it("skip any blocking approval in a habit run's chat, which the pill shows", () => {
    expect(pillShows(asking, true, approval({ session_id: "s1" }), new Set(["s1"]))).toBe(true);
  });
});
