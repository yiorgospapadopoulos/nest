// A pane of the Mac app (B124): the chat around it stays native, so what a row asks for
// goes to the app, and a busy pane handles only its own chat's streaming text.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { NestEvent } from "../../api/types.ts";
import { streamOfAnother } from "../../store/paneStream.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { detail, event, repo, session } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { paneBridge, type PaneMessage } from "../bridge.ts";
import { DesktopApp } from "../DesktopApp.tsx";
import { PANE_EVENT } from "./paneEvent.ts";
import { transcriptTarget } from "./transcriptTarget.ts";

function renderPane() {
  const chat = session({ id: "s1", state: "idle" });
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("todo-ui")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  api.sessionEvents.mockResolvedValue([
    event({ id: 7, type: "session.user_message", payload: { text: "Hello" } }),
  ]);
  const sent: PaneMessage[] = [];
  const post = (message: PaneMessage) => {
    sent.push(message);
    return Promise.resolve(undefined);
  };
  render(
    <DesktopApp
      bridge={paneBridge(post)}
      api={api}
      connect={socketFactory().connect}
      location={{ protocol: "http:", host: "127.0.0.1" }}
      storage={() => memoryStorage()}
      transcript={{ chat: "s1" }}
    />,
  );
  return { sent };
}

describe("a transcript page", () => {
  it("tells the app when it is ready, and shows the chat alone", async () => {
    const { sent } = renderPane();
    await screen.findByText("Hello");
    expect(sent).toContainEqual({ kind: "ready" });
    expect(document.querySelector(".dc-pane")).toBeNull();
  });

  it("leaves Rewind to the app, with the app's own sheet", async () => {
    const { sent } = renderPane();
    await screen.findByText("Hello");
    fireEvent.click(await screen.findByRole("button", { name: "Message actions" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Rewind/ }));
    await waitFor(() => {
      expect(sent).toContainEqual({ kind: "message", action: "rewind", event: 7 });
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("follows the app's accent", async () => {
    renderPane();
    await screen.findByText("Hello");
    act(() => {
      const detail = { kind: "appearance", theme: "dark", accent: "teal" };
      window.dispatchEvent(new CustomEvent(PANE_EVENT, { detail }));
    });
    await waitFor(() => {
      expect(document.documentElement.getAttribute("data-accent")).toBe("teal");
    });
  });
});

describe("a transcript page's address", () => {
  const target = (query: string) => transcriptTarget(new URLSearchParams(query));

  it("names a chat, a Claude Code chat or a work sheet's work", () => {
    expect(target("chat=c1")).toEqual({ chat: "c1" });
    expect(target("claude=x")).toEqual({ claude: "x" });
    expect(target("session=c1&pixie=p1")).toEqual({ work: { session: "c1", pixie: "p1" } });
    expect(target("session=c1&team=t1")).toEqual({ work: { session: "c1", team: "t1" } });
    expect(target("session=c1&call=u1")).toEqual({ work: { session: "c1", call: "u1" } });
  });

  it("shows nothing for an address that names none of them", () => {
    expect(target("")).toBeNull();
    expect(target("session=c1")).toBeNull();
  });
});

describe("keyboard scrolling in a pane", () => {
  const list = async () => {
    renderPane();
    await screen.findByText("Hello");
    const el = document.querySelector<HTMLElement>(".dc-tx");
    if (el === null) throw new Error("no transcript");
    Object.defineProperty(el, "clientHeight", { value: 500, configurable: true });
    Object.defineProperty(el, "scrollHeight", { value: 5000, configurable: true });
    el.scrollTop = 3000;
    return el;
  };

  it("moves a page at a time, whatever the list redraws meanwhile", async () => {
    const el = await list();
    fireEvent.keyDown(window, { key: "PageUp" });
    expect(el.scrollTop).toBe(2540);
    fireEvent.keyDown(window, { key: "PageDown" });
    expect(el.scrollTop).toBe(3000);
  });

  it("goes to either end", async () => {
    const el = await list();
    fireEvent.keyDown(window, { key: "Home" });
    expect(el.scrollTop).toBe(0);
    fireEvent.keyDown(window, { key: "End" });
    expect(el.scrollTop).toBe(5000);
  });

  it("leaves typing in a field and shortcuts alone", async () => {
    const el = await list();
    fireEvent.keyDown(window, { key: "PageUp", metaKey: true });
    expect(el.scrollTop).toBe(3000);
    const field = document.body.appendChild(document.createElement("textarea"));
    fireEvent.keyDown(field, { key: "Home" });
    expect(el.scrollTop).toBe(3000);
    field.remove();
  });
});

describe("a pane's event stream", () => {
  const of = (type: string, sessionId: string | null): NestEvent => ({
    id: null,
    type,
    ts: "2026-11-05T00:00:00Z",
    session_id: sessionId,
    payload: {},
  });

  it("drops only the streaming text of other chats", () => {
    expect(streamOfAnother(of("session.delta", "other"), "mine")).toBe(true);
    expect(streamOfAnother(of("session.thinking_delta", "other"), "mine")).toBe(true);
    expect(streamOfAnother(of("session.delta", "mine"), "mine")).toBe(false);
    expect(streamOfAnother(of("session.state", "other"), "mine")).toBe(false);
  });
});
