// The desktop chat pane's rules (B117 wave 2A): a long chat draws only what is on screen
// and keeps an opened row open across scrolling, follows the bottom and keeps the reader's
// place (the phone's Virtual tests, on the desktop pane); Run opens its output beside the
// chat; the composer's pickers set what the chat or the new chat runs with, and a new
// chat starts where its place picker says.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BranchMap, NestEvent, Session } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { detail, event, repo, runStatus, session } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { browserBridge } from "../bridge.ts";
import { DesktopApp } from "../DesktopApp.tsx";
import { ProjectState } from "../layout/project.ts";
import { EMPTY_DESK, saveDesk } from "../shell/desk.ts";
import { ScrollFollow } from "../../screens/chat/scrollFollow.ts";
import type { TranscriptItem } from "../../transcript/build.ts";
import { VirtualList } from "./VirtualList.tsx";

// jsdom lays nothing out: rows get heights from this table, the transcript a 300 px view,
// the workspace 1200 by 800, and scrolling is clamped and announced as a browser does it.
const ROW = 100;
const VIEW = 300;
const UNDER = 40;
const heights = new Map<string, number>();
const offsets = new WeakMap<Element, number>();
const moved = new Set<Element>();
const observers = new Set<FakeObserver>();

class FakeObserver {
  readonly targets = new Set<Element>();
  private readonly callback: ResizeObserverCallback;
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    observers.add(this);
  }
  observe(target: Element) {
    this.targets.add(target);
  }
  unobserve(target: Element) {
    this.targets.delete(target);
  }
  disconnect() {
    this.targets.clear();
    observers.delete(this);
  }
  notify() {
    const entries = [...this.targets]
      .filter((target) => target.isConnected)
      .map((target) => ({
        target,
        borderBoxSize: [{ blockSize: heightOf(target), inlineSize: 400 }],
      }));
    if (entries.length > 0) this.callback(entries as unknown as ResizeObserverEntry[], this);
  }
}

function heightOf(el: Element): number {
  if (el.classList.contains("dc-tx-row")) {
    const ev = el.querySelector<HTMLElement>("[data-ev]")?.dataset.ev ?? "";
    // An opened output makes its row taller.
    const open = el.querySelector(".dc-out") === null ? 0 : 200;
    return (heights.get(ev) ?? ROW) + open;
  }
  if (el.classList.contains("dc-tx")) return VIEW;
  return el.classList.contains("dk-work") ? 800 : 0;
}

function contentOf(el: Element): number {
  const list = el.querySelector<HTMLElement>(".dc-tx-v");
  return (list === null ? 0 : Number.parseFloat(list.style.height)) + UNDER;
}

const maxOffset = (el: Element) => Math.max(0, contentOf(el) - VIEW);
const saved = new Map<string, PropertyDescriptor | undefined>();
function override(name: string, descriptor: PropertyDescriptor) {
  const proto = name === "scrollTo" ? Element.prototype : HTMLElement.prototype;
  saved.set(name, Object.getOwnPropertyDescriptor(proto, name));
  Object.defineProperty(proto, name, { configurable: true, ...descriptor });
}

beforeEach(() => {
  heights.clear();
  observers.clear();
  moved.clear();
  localStorage.clear();
  vi.stubGlobal("ResizeObserver", FakeObserver);
  Element.prototype.scrollIntoView = () => undefined;
  override("offsetHeight", {
    get(this: HTMLElement) {
      return heightOf(this);
    },
  });
  override("clientHeight", {
    get(this: HTMLElement) {
      return this.classList.contains("dc-tx") ? VIEW : this.classList.contains("dk-work") ? 800 : 0;
    },
  });
  override("clientWidth", {
    get(this: HTMLElement) {
      if (this.classList.contains("dc-tx")) return 400;
      return this.classList.contains("dk-work") ? 1200 : 0;
    },
  });
  override("scrollHeight", {
    get(this: HTMLElement) {
      return this.classList.contains("dc-tx") ? contentOf(this) : 0;
    },
  });
  override("scrollTop", {
    get(this: HTMLElement) {
      return offsets.get(this) ?? 0;
    },
    set(this: HTMLElement, value: number) {
      const next = Math.min(Math.max(0, value), maxOffset(this));
      if (next !== (offsets.get(this) ?? 0)) moved.add(this);
      offsets.set(this, next);
    },
  });
  override("scrollTo", {
    value(this: HTMLElement, options: ScrollToOptions) {
      this.scrollTop = options.top ?? this.scrollTop;
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  for (const [name, descriptor] of saved) {
    const proto = name === "scrollTo" ? Element.prototype : HTMLElement.prototype;
    if (descriptor === undefined) Reflect.deleteProperty(proto, name);
    else Object.defineProperty(proto, name, descriptor);
  }
  saved.clear();
});

/** A frame: sizes are observed and a moved view fires its scroll, until all is still. */
async function frames(count = 6) {
  for (let i = 0; i < count; i++) {
    await act(async () => {
      for (const observer of [...observers]) observer.notify();
      for (const el of [...moved]) {
        moved.delete(el);
        el.dispatchEvent(new Event("scroll"));
      }
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
  }
}

async function scrollTo(box: HTMLElement, top: number) {
  box.scrollTop = top;
  moved.delete(box);
  fireEvent.scroll(box);
  await frames();
}

const atEnd = (box: HTMLElement) => box.scrollTop >= maxOffset(box) - 1;

function onScreen(box: HTMLElement, ev: string): number {
  const row = defined(box.querySelector(`[data-ev="${ev}"]`)?.closest<HTMLElement>(".dc-tx-row"));
  const y = Number(/translateY\((-?[\d.]+)px\)/.exec(row.style.transform)?.[1]);
  return y - box.scrollTop;
}

function firstShown(box: HTMLElement): string {
  for (const node of box.querySelectorAll<HTMLElement>(".dc-tx-row [data-ev]")) {
    const ev = defined(node.dataset.ev);
    if (onScreen(box, ev) >= 0) return ev;
  }
  throw new Error("nothing on screen");
}

const message = (id: number) =>
  event({
    id,
    type: "session.message",
    payload: { blocks: [{ type: "text", text: `Reply ${String(id)}` }], parent_tool_use_id: null },
  });
const replies = (from: number, to: number) =>
  Array.from({ length: to - from + 1 }, (_, i) => message(from + i));

interface Open {
  chats: Session[];
  panes: string[];
  events?: NestEvent[];
  api?: FakeApi;
}

/** The desktop window with `panes` open in the todo-ui tab, the last one focused. */
async function openDesktop({ chats, panes, events = [], api = fakeApi() }: Open) {
  api.repos.mockResolvedValue([{ ...repo("todo-ui"), current_branch: "redesign" }]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : chats));
  api.session.mockImplementation((id) =>
    Promise.resolve(detail(chats.find((c) => c.id === id) ?? chats[0])),
  );
  api.sessionEvents.mockResolvedValue(events);
  const project = new ProjectState();
  for (const pane of panes) project.openChat(pane, { width: 1200, height: 800 });
  saveDesk(localStorage, {
    ...EMPTY_DESK,
    tabs: { open: ["todo-ui"], current: "todo-ui", last: "todo-ui" },
    projects: { "todo-ui": project },
  });
  const sockets = socketFactory();
  const storage = memoryStorage();
  render(
    <DesktopApp
      bridge={browserBridge({ search: "" }, null)}
      api={api}
      connect={sockets.connect}
      location={{ protocol: "http:", host: "127.0.0.1:8765" }}
      storage={() => storage}
    />,
  );
  await screen.findByRole("button", { name: "Settings" });
  const push = (pushed: Partial<NestEvent> & { type: string }) => {
    act(() => {
      sockets.last().emit(pushed);
    });
  };
  return { api, push };
}

async function openLongChat(count: number, extra: NestEvent[] = []) {
  const chat = session({ state: "running", title: "Long chat" });
  const opened = await openDesktop({
    chats: [chat],
    panes: ["s1"],
    events: [...replies(1, count), ...extra],
  });
  await screen.findByText(`Reply ${String(count)}`);
  await frames();
  const box = defined(document.querySelector<HTMLElement>(".dc-tx"));
  const say = (id: number) => {
    opened.push({ ...message(id), session_id: "s1" });
  };
  return { ...opened, box, say };
}

describe("a long chat draws only what is on screen (B117)", () => {
  it("opens at its end and stays there while a reply streams and grows", async () => {
    const { box, say, push } = await openLongChat(400);
    expect(box).toHaveClass("virt");
    expect(box.querySelectorAll("[data-ev]").length).toBeLessThan(40);
    expect(atEnd(box)).toBe(true);
    push({ id: null, session_id: "s1", type: "session.delta", payload: { text: "Stream" } });
    await frames();
    expect(atEnd(box)).toBe(true);
    say(401);
    await frames();
    expect(within(box).getByText("Reply 401")).toBeInTheDocument();
    heights.set("401", 900);
    await frames();
    expect(atEnd(box)).toBe(true);
    expect(screen.queryByRole("button", { name: "Jump to latest" })).not.toBeInTheDocument();
  });

  it("keeps the reader's place when new items arrive and items above change height", async () => {
    const { box, say } = await openLongChat(400);
    await scrollTo(box, 15_000);
    const shown = firstShown(box);
    const place = onScreen(box, shown);
    expect(screen.getByRole("button", { name: "Jump to latest" })).toBeInTheDocument();
    say(401);
    await frames();
    expect(onScreen(box, shown)).toBe(place);
    const above = defined(box.querySelector<HTMLElement>(".dc-tx-row [data-ev]")?.dataset.ev);
    heights.set(above, ROW + 250);
    await frames();
    expect(onScreen(box, shown)).toBe(place);
    // Jump to latest goes back to the end and follows again.
    fireEvent.click(screen.getByRole("button", { name: "Jump to latest" }));
    await frames();
    expect(atEnd(box)).toBe(true);
  });

  it("keeps a row opened as the reader left it when it scrolls away and back", async () => {
    // A tool call near the top, its output folded until opened.
    const call = event({
      id: 1000,
      type: "session.message",
      payload: {
        blocks: [{ type: "tool_use", id: "t1", name: "Bash", input: { command: "ls" } }],
        parent_tool_use_id: null,
      },
    });
    const result = event({
      id: 1001,
      type: "session.message",
      payload: {
        blocks: [{ type: "tool_result", tool_use_id: "t1", content: "a\nb\nc" }],
        parent_tool_use_id: null,
      },
    });
    const chat = session({ state: "idle", title: "Long chat" });
    await openDesktop({
      chats: [chat],
      panes: ["s1"],
      events: [call, result, ...replies(2000, 2400)],
    });
    await screen.findByText("Reply 2400");
    await frames();
    const box = defined(document.querySelector<HTMLElement>(".dc-tx"));
    expect(box).toHaveClass("virt");
    await scrollTo(box, 0);
    const row = await within(box).findByRole("button", { name: /Bash/ });
    fireEvent.click(row);
    expect(box.querySelector(".dc-out pre")?.textContent).toBe("a\nb\nc");
    // Scrolled far away the row is not drawn at all; back at the top it is open.
    await scrollTo(box, 20_000);
    expect(within(box).queryByRole("button", { name: /Bash/ })).not.toBeInTheDocument();
    await scrollTo(box, 0);
    expect(await within(box).findByRole("button", { name: /Bash/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(box.querySelector(".dc-out pre")?.textContent).toBe("a\nb\nc");
  });
});

describe("Run (B108)", () => {
  it("opens the run's output beside the chat, keeps the focus in the chat and starts it", async () => {
    const api = fakeApi();
    api.run.mockResolvedValue(
      runStatus({ available: true, command: "npm run dev", folder: "/w/s1" }),
    );
    const chat = session({ title: "Validate contact form" });
    await openDesktop({ chats: [chat], panes: ["s1"], api });
    const pane = await screen.findByRole("region", { name: "Validate contact form" });
    fireEvent.click(await within(pane).findByRole("button", { name: "Run" }));
    await waitFor(() => {
      expect(document.querySelectorAll(".dk-pane")).toHaveLength(2);
    });
    expect(api.runControl).toHaveBeenCalledWith("s1", "start");
    const focused = defined(document.querySelector(".dk-pane.focused"));
    expect(
      within(focused as HTMLElement).getByRole("region", { name: "Validate contact form" }),
    ).toBeInTheDocument();
    // The output pane is beside the chat, to its right.
    const [left, right] = [...document.querySelectorAll<HTMLElement>(".dk-pane")];
    expect(Number.parseFloat(defined(right).style.left)).toBeGreaterThan(
      Number.parseFloat(defined(left).style.left),
    );
  });

  it("shows Run once the project gets a run command, and once the chat's worktree exists", async () => {
    // Wave 7: open panes kept their old Run state until they were opened again.
    const api = fakeApi();
    api.run.mockResolvedValue(runStatus({ available: false, command: null, folder: null }));
    const chat = session({ title: "Validate contact form", worktree_path: null });
    const { push } = await openDesktop({ chats: [chat], panes: ["s1"], api });
    const pane = await screen.findByRole("region", { name: "Validate contact form" });
    expect(within(pane).queryByRole("button", { name: "Run" })).toBeNull();

    api.run.mockResolvedValue(
      runStatus({ available: true, command: "npm run dev", folder: "/w/s1" }),
    );
    push({
      type: "repo.updated",
      session_id: null,
      payload: { name: "todo-ui", repo: repo("todo-ui") as never },
    });
    expect(await within(pane).findByRole("button", { name: "Run" })).toBeInTheDocument();

    const calls = api.run.mock.calls.length;
    push({
      type: "session.workspace",
      session_id: "s1",
      payload: { path: "/w/agent-s1", branch: "agent/s1" },
    });
    await waitFor(() => {
      expect(api.run.mock.calls.length).toBeGreaterThan(calls);
    });
  });
});

const map: BranchMap = {
  default_branch: "main",
  current_branch: "redesign",
  branches: [
    { name: "main", parent: null, worktree: null, here: false },
    { name: "redesign", parent: "main", worktree: null, here: true },
    {
      name: "agent/icons",
      parent: "redesign",
      worktree: { path: "/w/icons", owner: "nest" },
      here: false,
    },
  ],
};

async function newChat(api: FakeApi) {
  await openDesktop({ chats: [session({ title: "Other" })], panes: ["s1"], api });
  fireEvent.click(defined(screen.getAllByRole("button", { name: "New chat" })[0]));
  return screen.findByRole("region", { name: "New chat" });
}

function sendFirst(pane: HTMLElement, text: string) {
  const field = within(pane).getByRole("textbox", { name: "Message" });
  fireEvent.change(field, { target: { value: text } });
  fireEvent.keyDown(field, { key: "Enter" });
}

describe("a new chat's place (B55, B96)", () => {
  it("takes the keyboard when it opens, from the button and from Ctrl+N", async () => {
    const pane = await newChat(fakeApi());
    const field = within(pane).getByRole("textbox", { name: "Message" });
    await waitFor(() => {
      expect(field).toHaveFocus();
    });
    act(() => {
      field.blur();
    });
    fireEvent.keyDown(window, { key: "n", ctrlKey: true });
    await waitFor(() => {
      const fields = screen
        .getAllByRole("region", { name: "New chat" })
        .map((p) => within(p).getByRole("textbox", { name: "Message" }));
      expect(fields).toHaveLength(2);
      expect(fields.some((f) => f === document.activeElement && f !== field)).toBe(true);
    });
  });

  it("starts in a new worktree from the folder's branch with the typed branch name", async () => {
    const api = fakeApi();
    const pane = await newChat(api);
    // The project's default is a worktree; the menu offers the folder too.
    const button = within(pane).getByRole("button", {
      name: /^Where the chat works: New worktree from redesign/,
    });
    fireEvent.pointerDown(button, { button: 0 });
    fireEvent.click(await screen.findByRole("menuitemcheckbox", { name: "Work on redesign" }));
    fireEvent.pointerDown(
      within(pane).getByRole("button", { name: /^Where the chat works: Work on redesign/ }),
      { button: 0 },
    );
    fireEvent.click(await screen.findByRole("menuitemcheckbox", { name: "New worktree" }));
    fireEvent.change(within(pane).getByRole("textbox", { name: "Branch name, optional" }), {
      target: { value: " fix/copy " },
    });
    sendFirst(pane, "Fix the copy");
    await waitFor(() => {
      expect(api.createSession).toHaveBeenCalled();
    });
    expect(api.createSession.mock.calls[0]?.[0]).toMatchObject({
      repo: "todo-ui",
      prompt: "Fix the copy",
      mode: "worktree",
      base: "redesign",
      branch: "fix/copy",
    });
  });

  it("works in an existing worktree chosen from the branch map's picker", async () => {
    const api = fakeApi();
    api.branchMap.mockResolvedValue(map);
    const pane = await newChat(api);
    const button = await within(pane).findByRole("button", {
      name: /^Where the chat works/,
      expanded: false,
    });
    await waitFor(() => {
      expect(button).toHaveAttribute("aria-haspopup", "dialog");
    });
    fireEvent.click(button);
    fireEvent.click(await screen.findByRole("option", { name: "Work in worktree agent/icons" }));
    expect(
      within(pane).getByRole("button", { name: "Where the chat works: agent/icons" }),
    ).toBeInTheDocument();
    sendFirst(pane, "Draw the icons");
    await waitFor(() => {
      expect(api.createSession).toHaveBeenCalled();
    });
    expect(api.createSession.mock.calls[0]?.[0]).toMatchObject({
      mode: "worktree",
      worktree_path: "/w/icons",
    });
  });
});

describe("the composer's menus", () => {
  it("sets an open chat's model and its permission mode on the chat", async () => {
    const api = fakeApi();
    await openDesktop({ chats: [session({ title: "Chat" })], panes: ["s1"], api });
    const pane = await screen.findByRole("region", { name: "Chat" });
    fireEvent.pointerDown(await within(pane).findByRole("button", { name: /^Model:/ }), {
      button: 0,
    });
    fireEvent.click(await screen.findByRole("menuitemcheckbox", { name: "Haiku 4.5" }));
    await waitFor(() => {
      expect(api.updateSession).toHaveBeenCalledWith("s1", { model: "haiku" });
    });
    fireEvent.pointerDown(within(pane).getByRole("button", { name: /^Permission mode:/ }), {
      button: 0,
    });
    fireEvent.click(await screen.findByRole("menuitemcheckbox", { name: "Plan" }));
    await waitFor(() => {
      expect(api.updateSession).toHaveBeenCalledWith("s1", { permission_mode: "plan" });
    });
  });

  it("starts a new chat with the model and mode chosen before its first message", async () => {
    const api = fakeApi();
    const pane = await newChat(api);
    fireEvent.pointerDown(await within(pane).findByRole("button", { name: /^Model:/ }), {
      button: 0,
    });
    fireEvent.click(await screen.findByRole("menuitemcheckbox", { name: "Opus 4.6" }));
    fireEvent.pointerDown(within(pane).getByRole("button", { name: /^Permission mode:/ }), {
      button: 0,
    });
    fireEvent.click(await screen.findByRole("menuitemcheckbox", { name: "Accept edits" }));
    sendFirst(pane, "Go");
    await waitFor(() => {
      expect(api.createSession).toHaveBeenCalled();
    });
    expect(api.createSession.mock.calls[0]?.[0]).toMatchObject({
      model: "claude-opus-4-6",
      permission_mode: "acceptEdits",
    });
    expect(api.updateSession).not.toHaveBeenCalled();
  });

  it("opens the palette with /resume's search typed in, sending nothing", async () => {
    const api = fakeApi();
    const chats = [session({ title: "Fix the header" }), session({ id: "s2", title: "Tidy CSS" })];
    await openDesktop({ chats, panes: ["s1"], api });
    sendFirst(await screen.findByRole("region", { name: "Fix the header" }), "/resume header");
    const palette = await screen.findByRole("dialog", { name: "Search chats and commands" });
    expect(within(palette).getByRole("combobox")).toHaveValue("header");
    expect(within(palette).getByText("Fix the header")).toBeInTheDocument();
    expect(within(palette).queryByText("Tidy CSS")).toBeNull();
    expect(api.sendMessage).not.toHaveBeenCalled();
  });
});

describe("a user message's menu", () => {
  it("runs the first click's item in a pane that was not focused", async () => {
    const chats = [
      session({ state: "idle", title: "Read the readme" }),
      session({ id: "s2", state: "idle", title: "Other" }),
    ];
    await openDesktop({
      chats,
      panes: ["s1", "s2"],
      events: [
        event({ id: 1, type: "session.user_message", payload: { text: "Read README.md" } }),
        message(2),
      ],
    });
    const pane = await screen.findByRole("region", { name: "Read the readme" });
    const trigger = await within(pane).findByRole("button", { name: "Message actions" });
    // A cancelled pointerdown (the menu's button) gets no mouse events, as in WebKit.
    const click = (target: Element) => {
      const go = fireEvent.pointerDown(target, { button: 0 });
      if (go) fireEvent.mouseDown(target, { button: 0 });
      fireEvent.pointerUp(target, { button: 0 });
      if (go) fireEvent.mouseUp(target, { button: 0 });
      fireEvent.click(target, { button: 0, detail: 1 });
    };
    click(trigger);
    const rewind = await screen.findByRole("menuitem", { name: "Rewind…" });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    click(rewind);
    expect(await screen.findByRole("dialog", { name: "Rewind" })).toBeInTheDocument();
  });
});

const item = (n: number): TranscriptItem => ({
  kind: "assistant",
  key: String(n),
  text: `Reply ${String(n)}`,
});
const range = (from: number, to: number) =>
  Array.from({ length: to - from + 1 }, (_, i) => item(from + i));

/** The list in a scrolled view, read the way the transcript reads its scrolling. */
function Harness({
  initial,
  focus = null,
  onHit = () => undefined,
}: {
  initial: TranscriptItem[];
  focus?: number | null;
  onHit?: (target: HTMLElement) => void;
}) {
  const [items, setItems] = useState(initial);
  const follow = useRef(new ScrollFollow());
  const focused = useRef<number | null>(null);
  return (
    <>
      <button
        onClick={() => {
          setItems([...range(1, 200), ...items]);
        }}
      >
        Older
      </button>
      <div
        className="dc-tx"
        onScroll={(e) => {
          const el = e.currentTarget;
          follow.current.update({
            offset: el.scrollTop,
            viewport: el.clientHeight,
            content: el.scrollHeight,
          });
        }}
      >
        <VirtualList
          items={items}
          follow={follow}
          focus={focus}
          focused={focused}
          onHit={onHit}
          renderItem={(i) => (
            <div className="m-a" data-ev={i.key}>
              {i.kind === "assistant" ? i.text : ""}
            </div>
          )}
        />
      </div>
    </>
  );
}

describe("the long list (B117)", () => {
  it("keeps the reader's place when older items come in at the top", async () => {
    render(<Harness initial={range(201, 600)} />);
    const box = defined(document.querySelector<HTMLElement>(".dc-tx"));
    await frames();
    await scrollTo(box, 20_000);
    const shown = firstShown(box);
    const place = onScreen(box, shown);
    fireEvent.click(screen.getByRole("button", { name: "Older" }));
    await frames();
    expect(onScreen(box, shown)).toBe(place);
    expect(box.scrollTop).toBeGreaterThan(20_000);
  });

  it("brings a search hit that is not drawn yet on screen and shows it", async () => {
    const hits: string[] = [];
    render(
      <Harness
        initial={range(1, 400)}
        focus={12}
        onHit={(target) => {
          hits.push(target.dataset.ev ?? "");
        }}
      />,
    );
    const box = defined(document.querySelector<HTMLElement>(".dc-tx"));
    await frames(10);
    expect(hits).toEqual(["12"]);
    const place = onScreen(box, "12");
    expect(place).toBeGreaterThanOrEqual(-ROW);
    expect(place).toBeLessThan(VIEW);
  });
});
