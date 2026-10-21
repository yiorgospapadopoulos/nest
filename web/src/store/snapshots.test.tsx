import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Approval, ClaudeChat, NestEvent, JsonValue } from "../api/types.ts";
import { fakeApi } from "../test/fakeApi.ts";
import { approval, detail, event, session } from "../test/fixtures.ts";
import { memoryStorage, renderApp } from "../test/render.tsx";
import { createActions } from "./actions.ts";
import { reduce } from "./reducer.ts";
import { initialState, type Action, type State } from "./state.ts";

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const said = (id: number, text: string) =>
  event({ id, type: "session.message", payload: { blocks: [{ type: "text", text }] } });
const asJson = (a: Approval) => ({ ...a }) as unknown as JsonValue;

describe("a snapshot that loads while live events arrive", () => {
  it("keeps the state of a turn that ended while the chat's history loaded", async () => {
    const chat = session({ state: "running" });
    const api = fakeApi();
    api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
    api.session.mockResolvedValue(detail(chat));
    const history = deferred<NestEvent[]>();
    api.sessionEvents.mockReturnValue(history.promise);
    const { user, push } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Chats" }));
    await user.click(screen.getByRole("button", { name: /^Validate contact form,/ }));
    const region = await screen.findByRole("region", { name: chat.title });

    push({
      id: 10,
      session_id: "s1",
      type: "session.state",
      payload: { state: "idle", duration_ms: 5000 },
    });
    await act(async () => {
      history.resolve([said(1, "First")]);
      await history.promise;
    });

    expect(await screen.findByText("First", { selector: ".tx *" })).toBeInTheDocument();
    expect(within(region).getByRole("img", { name: "Idle" })).toBeInTheDocument();
    expect(screen.queryByText(/^Working/)).not.toBeInTheDocument();
  });

  it("keeps an approval created during a resync and drops one resolved meanwhile", async () => {
    const api = fakeApi();
    api.sessions.mockImplementation((archived) =>
      Promise.resolve(archived ? [] : [session({ state: "running" })]),
    );
    const { sockets, push } = await renderApp({ api });
    // The resync's snapshot still lists q8, which is answered while it loads.
    const answered = approval({ id: "q8", payload: { tool: "Bash", input: { command: "ls" } } });
    api.approvals.mockResolvedValue([answered]);
    const chats = deferred<ClaudeChat[]>();
    api.claudeChats.mockReturnValue(chats.promise);
    act(() => {
      sockets.last().open();
    });

    push({
      id: 5,
      session_id: "s1",
      type: "approval.created",
      payload: { approval: asJson(approval()) },
    });
    push({
      id: 6,
      session_id: "s1",
      type: "approval.resolved",
      payload: { approval: asJson({ ...answered, status: "resolved" }) },
    });
    await act(async () => {
      chats.resolve([]);
      await chats.promise;
    });
    await waitFor(() => {
      expect(api.claudeChats).toHaveBeenCalledTimes(2);
    });

    expect(await screen.findByText("Permission · Bash npm install zod")).toBeInTheDocument();
    expect(screen.queryByText("ls")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Needs you 1" })).toBeInTheDocument();
  });
});

/** The actions over a plain reducer, without React. */
function store() {
  const api = fakeApi();
  let state: State = initialState;
  const actions = createActions(
    api,
    (action: Action) => {
      state = reduce(state, action);
    },
    () => memoryStorage(),
  );
  return { api, actions, state: () => state };
}

describe("a closed chat", () => {
  it("leaves memory and takes no more live events", async () => {
    const { api, actions, state } = store();
    api.sessionEvents.mockResolvedValue([said(1, "First")]);
    await actions.openChat("s1");
    expect(state().transcripts.s1).toHaveLength(1);

    actions.closeChat("s1");
    actions.receive(said(2, "Second"));

    expect(state().transcripts.s1).toBeUndefined();
  });

  it("stays out of memory when its history arrives after it closed", async () => {
    const { api, actions, state } = store();
    const history = deferred<NestEvent[]>();
    api.sessionEvents.mockReturnValue(history.promise);
    const opening = actions.openChat("s1");

    actions.closeChat("s1");
    history.resolve([said(1, "First")]);
    await opening;

    expect(state().transcripts.s1).toBeUndefined();
    expect(state().sessions.s1).toBeDefined();
  });
});
