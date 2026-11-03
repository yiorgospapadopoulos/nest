// A question's two cards, in the chat and in Needs you, share what was chosen, as the
// Mac's ApprovalsStore keeps one choice per question.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { StoreProvider } from "../../store/StoreProvider.tsx";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { question } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { ApprovalCard } from "./ApprovalCard.tsx";

beforeAll(() => {
  // jsdom lays nothing out.
  Element.prototype.scrollIntoView = () => undefined;
});

describe("a question's cards", () => {
  it("show the same choice and Other's text in the chat and in Needs you", () => {
    const asked = question({ id: "shared-q" });
    const storage = memoryStorage();
    render(
      <StoreProvider
        api={fakeApi()}
        connect={socketFactory().connect}
        storage={() => storage}
        location={{ protocol: "http:", host: "127.0.0.1:8765" }}
      >
        <section aria-label="Chat">
          <ApprovalCard approval={asked} style="inline" />
        </section>
        <section aria-label="Needs you">
          <ApprovalCard approval={asked} style="panel" />
        </section>
      </StoreProvider>,
    );
    const chat = within(screen.getByRole("region", { name: "Chat" }));
    const panel = within(screen.getByRole("region", { name: "Needs you" }));
    expect(panel.getByRole("radio", { name: /DAG/ })).toHaveAttribute("aria-checked", "true");

    fireEvent.click(chat.getByRole("radio", { name: /Other/ }));
    expect(panel.getByRole("radio", { name: /Other/ })).toHaveAttribute("aria-checked", "true");
    expect(panel.getByRole("radio", { name: /DAG/ })).toHaveAttribute("aria-checked", "false");
    // Only the card where Other was chosen takes the keyboard.
    expect(chat.getByRole("textbox", { name: "Type your answer" })).toHaveFocus();

    fireEvent.change(chat.getByRole("textbox", { name: "Type your answer" }), {
      target: { value: "A forest" },
    });
    expect(panel.getByRole("textbox", { name: "Type your answer" })).toHaveValue("A forest");
    expect(panel.getByRole("button", { name: "Send answer" })).toBeEnabled();
  });
});
