// Computer use on a pane (B150): the live strip while the chat holds an app, its Stop,
// and the card asking to use an app.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { beforeEach, describe, expect, it, type Mock, vi } from "vitest";
import { COMPUTER_FRAME, COMPUTER_STATE } from "../../api/events.ts";
import { useStore } from "../../store/context.ts";
import { StoreProvider } from "../../store/StoreProvider.tsx";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { approval, detail, session } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { ApprovalCard } from "./ApprovalCard.tsx";
import { Composer } from "./Composer.tsx";

function OpenChat({ children }: { children: ReactNode }) {
  const { actions } = useStore();
  useEffect(() => {
    void actions.openChat("s1");
  }, [actions]);
  return children;
}

function renderPane(api: FakeApi) {
  const sockets = socketFactory();
  const storage = memoryStorage();
  render(
    <StoreProvider
      api={api}
      connect={sockets.connect}
      storage={() => storage}
      location={{ protocol: "http:", host: "127.0.0.1:8765" }}
    >
      <OpenChat>
        <Composer target={{ kind: "chat", session: session() }} />
      </OpenChat>
    </StoreProvider>,
  );
  act(() => {
    sockets.last().open();
  });
  return sockets;
}

function enabledApi(): FakeApi {
  const api = fakeApi();
  api.computerSettings.mockResolvedValue({ enabled: true, pixies: false });
  api.session.mockResolvedValue(detail(session()));
  return api;
}

let made = 0;
let revoked: Mock<(url: string) => void>;
beforeEach(() => {
  made = 0;
  vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:frame${String(++made)}`);
  revoked = vi.fn<(url: string) => void>();
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(revoked);
});

describe("computer use on a pane (B150)", () => {
  it("shows the strip while the chat holds an app, with each new frame, and Stop", async () => {
    const api = enabledApi();
    const sockets = renderPane(api);
    await waitFor(() => {
      expect(api.sessionEvents).toHaveBeenCalled();
    });
    // The transcript's load lands before the socket's events count.
    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      sockets.last().emit({
        id: 5,
        session_id: "s1",
        type: COMPUTER_STATE,
        payload: { targets: [{ key: "mac:com.apple.TextEdit", name: "TextEdit" }] },
      });
    });
    const strip = await screen.findByRole("group", { name: "Using TextEdit" });
    await waitFor(() => {
      expect(strip.querySelector("img")).toHaveAttribute("src", "blob:frame1");
    });

    act(() => {
      sockets.last().emit({
        session_id: "s1",
        type: COMPUTER_FRAME,
        payload: { target: "mac:com.apple.TextEdit", label: "TextEdit", seq: 2 },
      });
    });
    await waitFor(() => {
      expect(strip.querySelector("img")).toHaveAttribute("src", "blob:frame2");
    });
    expect(api.computerFrame).toHaveBeenCalledTimes(2);
    expect(revoked).toHaveBeenCalledWith("blob:frame1");

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(api.stopComputerUse).toHaveBeenCalledWith("s1");

    act(() => {
      sockets.last().emit({
        id: 6,
        session_id: "s1",
        type: COMPUTER_STATE,
        payload: { targets: [] },
      });
    });
    expect(screen.queryByRole("group", { name: "Using TextEdit" })).not.toBeInTheDocument();
  });

  it("asks to use an app with Allow and Deny only", async () => {
    const api = fakeApi();
    const storage = memoryStorage();
    render(
      <StoreProvider
        api={api}
        connect={socketFactory().connect}
        storage={() => storage}
        location={{ protocol: "http:", host: "127.0.0.1:8765" }}
      >
        <ApprovalCard
          style="panel"
          approval={approval({
            payload: {
              tool: "computer_use",
              input: { target: "mac:com.apple.TextEdit" },
              title: "Let this chat use TextEdit?",
              reason: null,
              always_rule: null,
              always: false,
              computer: { target: "mac:com.apple.TextEdit", name: "TextEdit", kind: "use" },
            },
          })}
        />
      </StoreProvider>,
    );

    expect(screen.getByText("Let this chat use TextEdit?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Always allow" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Allow" }));

    await waitFor(() => {
      expect(api.resolveApproval).toHaveBeenCalledWith(
        "q1",
        expect.objectContaining({ behavior: "allow" }),
      );
    });
  });
});
