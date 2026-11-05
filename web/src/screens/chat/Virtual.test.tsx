import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SearchHit } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { detail, event, NOW, repo, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";
import type { TranscriptItem } from "../../transcript/build.ts";
import { ScrollFollow } from "./scrollFollow.ts";
import { VirtualItems } from "./VirtualItems.tsx";
import { VIRTUAL_FROM } from "./virtualRows.ts";

// jsdom lays nothing out: rows get heights from this table, the transcript a 300 px view,
// and scrolling is clamped and announced the way a browser does it.
const ROW = 100;
const VIEW = 300;
// What is under the list: padding, the working line.
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
      .map((target) => {
        const blockSize = heightOf(target);
        return { target, borderBoxSize: [{ blockSize, inlineSize: 400 }] };
      });
    if (entries.length > 0) {
      this.callback(entries as unknown as ResizeObserverEntry[], this);
    }
  }
}

function heightOf(el: Element): number {
  if (el.classList.contains("tx-row")) {
    const ev = el.querySelector<HTMLElement>("[data-ev]")?.dataset.ev ?? "";
    return heights.get(ev) ?? ROW;
  }
  return el.classList.contains("ch-tx") ? VIEW : 0;
}

function contentOf(el: Element): number {
  const list = el.querySelector<HTMLElement>(".tx-v");
  return (list === null ? 0 : Number.parseFloat(list.style.height)) + UNDER;
}

const maxOffset = (el: Element) => Math.max(0, contentOf(el) - VIEW);

const saved = new Map<string, PropertyDescriptor | undefined>();
function override(name: string, descriptor: PropertyDescriptor) {
  const proto = name === "scrollTo" ? Element.prototype : HTMLElement.prototype;
  saved.set(name, Object.getOwnPropertyDescriptor(proto, name));
  Object.defineProperty(proto, name, { configurable: true, ...descriptor });
}

const scrollIntoView = vi.fn();

beforeEach(() => {
  heights.clear();
  observers.clear();
  moved.clear();
  vi.stubGlobal("ResizeObserver", FakeObserver);
  scrollIntoView.mockClear();
  Element.prototype.scrollIntoView = scrollIntoView;
  override("offsetHeight", {
    get(this: HTMLElement) {
      return heightOf(this);
    },
  });
  override("clientHeight", {
    get(this: HTMLElement) {
      return this.classList.contains("ch-tx") ? VIEW : 0;
    },
  });
  override("clientWidth", {
    get(this: HTMLElement) {
      return this.classList.contains("ch-tx") ? 400 : 0;
    },
  });
  override("scrollHeight", {
    get(this: HTMLElement) {
      return this.classList.contains("ch-tx") ? contentOf(this) : 0;
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

/** The reader scrolls the view to `top`. */
async function scrollTo(box: HTMLElement, top: number) {
  box.scrollTop = top;
  moved.delete(box);
  fireEvent.scroll(box);
  await frames();
}

const atEnd = (box: HTMLElement) => box.scrollTop >= maxOffset(box) - 1;

/** Where an item's row is on screen, from the top of the view. */
function onScreen(box: HTMLElement, ev: string): number {
  const row = defined(box.querySelector(`[data-ev="${ev}"]`)?.closest<HTMLElement>(".tx-row"));
  const y = Number(/translateY\((-?[\d.]+)px\)/.exec(row.style.transform)?.[1]);
  return y - box.scrollTop;
}

/** The first item drawn on screen. */
function firstShown(box: HTMLElement): string {
  for (const node of box.querySelectorAll<HTMLElement>(".tx-row [data-ev]")) {
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

async function openChat(count: number, chat = session({ state: "running" })) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("todo-ui")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.sessionEvents.mockResolvedValue(replies(1, count));
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByText(`Reply ${String(count)}`);
  await frames();
  const box = defined(document.querySelector<HTMLElement>(".ch-tx"));
  const say = (id: number) => {
    rendered.push({ ...message(id), session_id: "s1" });
  };
  return { ...rendered, box, say };
}

describe("long chats draw only what is on screen (B117)", () => {
  it("leaves a chat under the threshold as it was: every item in the page", async () => {
    const { box } = await openChat(VIRTUAL_FROM - 1);
    expect(box).not.toHaveClass("virt");
    expect(box.querySelector(".tx-row")).toBeNull();
    expect(box.querySelectorAll(".tx > .m-a")).toHaveLength(VIRTUAL_FROM - 1);
  });

  it("opens a long chat at its end and stays there while a reply streams and grows", async () => {
    const { box, say, push } = await openChat(400);
    expect(box).toHaveClass("virt");
    expect(box.querySelectorAll("[data-ev]").length).toBeLessThan(40);
    expect(within(box).getByText("Reply 400")).toBeInTheDocument();
    expect(atEnd(box)).toBe(true);

    push({ id: null, session_id: "s1", type: "session.delta", payload: { text: "Stream" } });
    await frames();
    expect(atEnd(box)).toBe(true);

    say(401);
    await frames();
    expect(within(box).getByText("Reply 401")).toBeInTheDocument();
    expect(atEnd(box)).toBe(true);

    // The newest item is measured taller once drawn (a long answer, an image loading).
    heights.set("401", 900);
    await frames();
    expect(atEnd(box)).toBe(true);
    expect(screen.queryByRole("button", { name: "Jump to latest" })).not.toBeInTheDocument();
  });

  it("keeps the reader's place when new items arrive and items above change height", async () => {
    const { box, say } = await openChat(400);
    await scrollTo(box, 15_000);
    const shown = firstShown(box);
    const place = onScreen(box, shown);
    expect(screen.getByRole("button", { name: "Jump to latest" })).toBeInTheDocument();

    say(401);
    say(402);
    await frames();
    expect(onScreen(box, shown)).toBe(place);

    // An item drawn above the screen grows (tool output streaming in, an image).
    const above = defined(box.querySelector<HTMLElement>(".tx-row [data-ev]")?.dataset.ev);
    expect(onScreen(box, above)).toBeLessThan(0);
    heights.set(above, ROW + 250);
    await frames();
    expect(onScreen(box, shown)).toBe(place);

    // And shrinks again.
    heights.set(above, ROW - 60);
    await frames();
    expect(onScreen(box, shown)).toBe(place);
  });

  it("jumps to a search hit that is not drawn yet and holds it there", async () => {
    const api = fakeApi();
    const chat = session();
    api.repos.mockResolvedValue([repo("todo-ui")]);
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
    api.session.mockResolvedValue(detail(chat));
    api.sessionEvents.mockResolvedValue(replies(1, 400));
    const hit: SearchHit = {
      session_id: "s1",
      repo: "todo-ui",
      title: chat.title,
      event_id: 12,
      ts: NOW,
      kind: "assistant",
      snippet: "[[Reply]] 12",
    };
    api.search.mockResolvedValue({ hits: [hit], indexing: false });
    const { user, push } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.type(screen.getByRole("searchbox", { name: "Search chats" }), "Reply");
    await user.click(await screen.findByRole("button", { name: /^ClaudeReply 12/ }));
    await frames(10);

    const target = defined((await screen.findByText("Reply 12")).closest<HTMLElement>(".m-a"));
    await waitFor(() => {
      expect(target).toHaveClass("hit");
    });
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "center" });
    const box = defined(document.querySelector<HTMLElement>(".ch-tx"));
    expect(box).toHaveClass("virt");
    const place = onScreen(box, "12");
    expect(place).toBeGreaterThanOrEqual(0);
    expect(place).toBeLessThan(VIEW);

    // New output does not pull the reader away from the hit.
    push({ ...message(401), session_id: "s1" });
    await frames();
    expect(onScreen(box, "12")).toBe(place);
  });
});

describe("a search hit in a call folded to its line", () => {
  it("opens the line, for a hit on the call's result too", async () => {
    const api = fakeApi();
    const chat = session();
    const call = event({
      id: 5,
      type: "session.message",
      payload: {
        blocks: [{ type: "tool_use", id: "t1", name: "Bash", input: { command: "ls" } }],
        parent_tool_use_id: null,
      },
    });
    const output = event({
      id: 6,
      type: "session.message",
      payload: {
        blocks: [{ type: "tool_result", tool_use_id: "t1", content: "needle" }],
        parent_tool_use_id: null,
      },
    });
    api.repos.mockResolvedValue([repo("todo-ui")]);
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
    api.session.mockResolvedValue(detail(chat));
    api.sessionEvents.mockResolvedValue([...replies(1, 4), call, output, ...replies(7, 9)]);
    const hit: SearchHit = {
      session_id: "s1",
      repo: "todo-ui",
      title: chat.title,
      event_id: 6,
      ts: NOW,
      kind: "tool_result",
      snippet: "[[needle]]",
    };
    api.search.mockResolvedValue({ hits: [hit], indexing: false });
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.type(screen.getByRole("searchbox", { name: "Search chats" }), "needle");
    await user.click(await screen.findByRole("button", { name: /needle/ }));

    const line = defined((await screen.findByText("Ran 1 command")).closest("details"));
    await waitFor(() => {
      expect(line).toHaveClass("hit");
    });
    expect(line.open).toBe(true);
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
function Harness({ initial }: { initial: TranscriptItem[] }) {
  const [items, setItems] = useState(initial);
  const box = useRef<HTMLDivElement>(null);
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
        className="ch-tx"
        ref={box}
        onScroll={(e) => {
          const el = e.currentTarget;
          follow.current.update({
            offset: el.scrollTop,
            viewport: el.clientHeight,
            content: el.scrollHeight,
          });
        }}
      >
        <div className="tx">
          <VirtualItems
            items={items}
            follow={follow}
            focus={null}
            focused={focused}
            onHit={() => undefined}
            renderItem={(i) => (
              <div className="m-a" data-ev={i.key}>
                {i.kind === "assistant" ? i.text : ""}
              </div>
            )}
          />
        </div>
      </div>
    </>
  );
}

describe("older items coming in at the top (B117)", () => {
  it("keeps the reader's place", async () => {
    render(<Harness initial={range(201, 600)} />);
    const box = defined(document.querySelector<HTMLElement>(".ch-tx"));
    await frames();
    await scrollTo(box, 20_000);
    const shown = firstShown(box);
    const place = onScreen(box, shown);

    fireEvent.click(screen.getByRole("button", { name: "Older" }));
    await frames();
    expect(onScreen(box, shown)).toBe(place);
    expect(box.scrollTop).toBeGreaterThan(20_000);
  });
});
