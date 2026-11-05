// The Linux app draws its own Autopilot controls over the logic it shares with the phone.
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { StoreProvider } from "../../store/StoreProvider.tsx";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { autopilotDecision, autopilotReport, autopilotRun, session } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { AutopilotReportCard, DecisionLine } from "./Autopilot.tsx";
import { Composer } from "./Composer.tsx";

function renderWith(api: ReturnType<typeof fakeApi>, children: ReactNode) {
  const storage = memoryStorage();
  render(
    <StoreProvider
      api={api}
      connect={socketFactory().connect}
      storage={() => storage}
      location={{ protocol: "http:", host: "127.0.0.1:8765" }}
    >
      {children}
    </StoreProvider>,
  );
}

const radio = (name: string) => screen.getByRole("radio", { name });

describe("Autopilot on a pane (B120)", () => {
  it("turns on with the budget chosen in the popover", () => {
    const api = fakeApi();
    renderWith(api, <Composer target={{ kind: "chat", session: session() }} />);

    fireEvent.click(screen.getByRole("button", { name: "Autopilot: off" }));
    fireEvent.click(radio("Time"));
    fireEvent.click(radio("8 h"));
    fireEvent.click(radio("50%"));
    expect(api.setAutopilot).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("switch", { name: "Autopilot" }));

    expect(api.setAutopilot).toHaveBeenCalledWith("s1", {
      on: true,
      stop_after_minutes: 480,
      weekly_cap: 50,
    });
  });

  it("offers no Autopilot on a pixie's page before it has a chat", () => {
    renderWith(fakeApi(), <Composer target={{ kind: "pixie", pixie: "p1", session: undefined }} />);

    expect(screen.queryByRole("button", { name: "Autopilot: off" })).not.toBeInTheDocument();
  });

  it("locks the mode on Bypass during a run", async () => {
    const api = fakeApi();
    renderWith(
      api,
      <Composer target={{ kind: "chat", session: session({ autopilot: autopilotRun() }) }} />,
    );

    expect(await screen.findByRole("button", { name: "Permission mode: Bypass" })).toBeDisabled();
  });

  it("opens a decision to its options and reason, a plan to its text", () => {
    const question = autopilotDecision({
      options: [
        { label: "3000", description: "The default", picked: false },
        { label: "8080", description: "Free here", picked: true },
      ],
      reason: "The agent recommended it: Free here",
    });
    const plan = autopilotDecision({
      kind: "plan",
      title: "The plan",
      answer: "Approved",
      detail: "First the tests",
    });
    renderWith(
      fakeApi(),
      <>
        <DecisionLine decision={question} chat="opens" id="1" />
        <DecisionLine decision={plan} chat="opens" id="2" />
        <DecisionLine decision={autopilotDecision({ title: "Bare" })} chat="opens" id="3" />
      </>,
    );

    expect(screen.queryByText("Free here")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Which port/ }));
    expect(screen.getByText("Free here")).toBeInTheDocument();
    expect(screen.getByText("The agent recommended it: Free here")).toBeInTheDocument();
    expect(screen.getByText("8080", { selector: "li b" }).closest("li")).toHaveClass("on");
    fireEvent.click(screen.getByRole("button", { name: /The plan/ }));
    expect(screen.getByText("First the tests")).toBeInTheDocument();
    // Nothing to open.
    expect(screen.getByRole("button", { name: /Bare/ })).toBeDisabled();
  });

  it("shows how a run ended and a denied decision apart, with no way to dismiss it", () => {
    const report = autopilotReport({
      ended: "stuck",
      decisions: [
        autopilotDecision({ kind: "allowed", title: "Edit .claude", answer: "Allowed" }),
        // Stored before decisions kept a reason: the answer says why.
        autopilotDecision({ kind: "denied", title: "git push", answer: "Blocked" }),
      ],
    });
    renderWith(fakeApi(), <AutopilotReportCard report={report} chat="s1" id="7" />);

    const card = screen.getByRole("group", { name: "Autopilot report" });
    expect(within(card).getByText("Got stuck")).toBeInTheDocument();
    const decided = within(card).getAllByRole("listitem");
    expect(decided[1]).toHaveTextContent("git push Denied");
    fireEvent.click(within(card).getByRole("button", { name: /git push/ }));
    expect(within(card).getByText("Blocked")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
  });
});
