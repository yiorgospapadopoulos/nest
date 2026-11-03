// The approve sheet as the Mac's PublishSheet: which choices show per chat, what Approve
// sends for each, the step list with a failed step's output, and the done toast.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { NestEvent, Session } from "../../api/types.ts";
import { useReview } from "../../screens/approvals/hooks.ts";
import { useStore } from "../../store/context.ts";
import { StoreProvider } from "../../store/StoreProvider.tsx";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { prStatus, review, session } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { ApiContext } from "../context.ts";
import { PublishSheet } from "./PublishSheet.tsx";

const ap = review({ title: "Dark mode contrast" });

function Harness({ chat, commitOnly }: { chat: Session; commitOnly: boolean }) {
  const { state } = useStore();
  const shown = useReview(ap, chat);
  return (
    <>
      <PublishSheet
        approval={ap}
        session={chat}
        review={shown}
        commitOnly={commitOnly}
        onClose={() => undefined}
      />
      <output aria-label="Toast">{state.toast?.text ?? ""}</output>
    </>
  );
}

async function open(chat: Session, { commitOnly = false, api = fakeApi() } = {}) {
  const sockets = socketFactory();
  const storage = memoryStorage();
  render(
    <StoreProvider
      api={api}
      connect={sockets.connect}
      storage={() => storage}
      location={{ protocol: "http:", host: "127.0.0.1:8765" }}
    >
      <ApiContext value={api}>
        <Harness chat={chat} commitOnly={commitOnly} />
      </ApiContext>
    </StoreProvider>,
  );
  const sheet = await screen.findByRole("dialog");
  // Approve waits for the changes.
  await waitFor(() => {
    expect(within(sheet).queryByText("Reading the changes…")).toBeNull();
  });
  const push = (event: Partial<NestEvent> & { type: string }) => {
    act(() => {
      sockets.last().emit(event);
    });
  };
  return { api, sheet: within(sheet), push };
}

const sent = (api: FakeApi) => api.approve.mock.calls.at(-1)?.[1];

describe("the approve sheet", () => {
  it("offers the pull request switch and fields for a worktree chat, and sends them", async () => {
    const { api, sheet } = await open(session());
    const toggle = sheet.getByRole("switch", { name: "Push and open a pull request" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.change(sheet.getByLabelText("Pull request title (optional)"), {
      target: { value: "Better contrast" },
    });
    fireEvent.change(sheet.getByLabelText("Pull request description (optional)"), {
      target: { value: "Raises it" },
    });
    fireEvent.click(sheet.getByRole("button", { name: "Approve and open PR" }));
    await waitFor(() => {
      expect(sent(api)).toMatchObject({
        push: true,
        open_pr: true,
        pr_title: "Better contrast",
        pr_body: "Raises it",
      });
    });
    expect(await screen.findByLabelText("Toast")).toHaveTextContent(
      "Opened a pull request for Dark mode contrast",
    );
  });

  it("approves and commits without pushing once the switch is off", async () => {
    const { api, sheet } = await open(session());
    fireEvent.click(sheet.getByRole("switch", { name: "Push and open a pull request" }));
    expect(sheet.queryByLabelText("Pull request title (optional)")).toBeNull();
    expect(sheet.getByText("Commits to agent/contact, not pushed")).toBeInTheDocument();
    fireEvent.click(sheet.getByRole("button", { name: "Approve and commit" }));
    await waitFor(() => {
      expect(sent(api)).toMatchObject({ push: false, open_pr: false });
    });
    expect(sent(api)).not.toHaveProperty("pr_title");
    expect(await screen.findByLabelText("Toast")).toHaveTextContent(
      "Committed Dark mode contrast without pushing",
    );
  });

  it("has no switch in place, says why, and commits the reviewed files", async () => {
    const { api, sheet } = await open(session({ mode: "in_place" }));
    expect(sheet.queryByRole("switch")).toBeNull();
    expect(sheet.getByText(/works in the project folder/)).toBeInTheDocument();
    fireEvent.click(sheet.getByRole("button", { name: "Approve and commit" }));
    await waitFor(() => {
      expect(sent(api)).toMatchObject({
        files: ["a.css", "b.tsx", "c.tsx"],
        push: false,
        open_pr: false,
      });
    });
  });

  it("with an open pull request offers push to it and commit only", async () => {
    const chat = session({
      pr_url: "https://github.com/me/cv/pull/8",
      pr: prStatus({ number: 8 }),
    });
    const { api, sheet } = await open(chat);
    expect(sheet.queryByRole("switch")).toBeNull();
    fireEvent.click(sheet.getByRole("button", { name: "Approve and commit" }));
    await waitFor(() => {
      expect(sent(api)).toMatchObject({ push: false, open_pr: false });
    });
    fireEvent.click(sheet.getByRole("button", { name: "Approve and push to #8" }));
    await waitFor(() => {
      expect(sent(api)).toMatchObject({ push: true, open_pr: false });
    });
  });

  it("shows each step and a failed push's output, and offers Try again", async () => {
    const api = fakeApi();
    let fail: (error: unknown) => void = () => undefined;
    api.approve.mockImplementation(
      () =>
        new Promise((_, reject) => {
          fail = reject;
        }),
    );
    const { sheet, push } = await open(session(), { api });
    fireEvent.click(sheet.getByRole("button", { name: "Approve and open PR" }));
    const steps = within(await sheet.findByLabelText("Approve steps"));
    push({ type: "git.committed", session_id: "s1", payload: { sha: "abc" } });
    expect(steps.getByText("Done")).toBeInTheDocument();
    act(() => {
      fail(new ApiError(502, "git push failed", null, { step: "push", stderr: "403 denied" }));
    });
    expect(await steps.findByText("403 denied")).toBeInTheDocument();
    expect(steps.getByText("Failed")).toBeInTheDocument();
    expect(steps.getByText("Waiting")).toBeInTheDocument();
    expect(sheet.getByRole("button", { name: "Try again" })).toBeEnabled();
  });
});
