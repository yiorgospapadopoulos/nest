// Which chats are using an app now (B150), for the mark on their rows.
import { describe, expect, it } from "vitest";
import { COMPUTER_STATE } from "../api/events.ts";
import { event } from "../test/fixtures.ts";
import { applyEvent } from "./reducer.ts";
import { initialState } from "./state.ts";

describe("computerUsing", () => {
  it("marks a chat while it holds an app and clears it when it lets go", () => {
    const held = applyEvent(
      initialState,
      event({
        id: 1,
        session_id: "s1",
        type: COMPUTER_STATE,
        payload: { targets: [{ key: "mac:com.apple.TextEdit", name: "TextEdit" }] },
      }),
    );
    expect(held.computerUsing).toEqual({ s1: true });

    const released = applyEvent(
      held,
      event({ id: 2, session_id: "s1", type: COMPUTER_STATE, payload: { targets: [] } }),
    );
    expect(released.computerUsing).toEqual({});
  });
});
