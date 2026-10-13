import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Inbox } from "../screens/inbox/Inbox.tsx";
import { useStore } from "../store/context.ts";
import { StoreProvider } from "../store/StoreProvider.tsx";
import { fakeApi } from "../test/fakeApi.ts";
import { socketFactory } from "../test/fakeSocket.ts";
import { approval } from "../test/fixtures.ts";
import { Toast, TOAST_MS } from "./Toast.tsx";
import { DiffStats } from "./bits.tsx";
import { toolIcon } from "./toolIcon.ts";
import { ActionSheet, Sheet } from "./Sheet.tsx";

describe("Sheet", () => {
  it("keeps Tab inside and returns focus to the opener", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { rerender } = render(<button>Opener</button>);
    screen.getByRole("button", { name: "Opener" }).focus();
    rerender(
      <>
        <button>Opener</button>
        <Sheet title="Pick" onClose={onClose} footer={<button>Go</button>}>
          <input aria-label="Field" />
        </Sheet>
      </>,
    );
    const field = screen.getByLabelText("Field");
    const done = screen.getByRole("button", { name: "Done" });
    const go = screen.getByRole("button", { name: "Go" });

    expect(done).toHaveFocus();
    await user.tab();
    expect(field).toHaveFocus();
    await user.tab();
    expect(go).toHaveFocus();
    await user.tab();
    expect(done).toHaveFocus();
    await user.tab({ shift: true });
    expect(go).toHaveFocus();
    await user.tab({ shift: true });
    expect(field).toHaveFocus();
    await user.keyboard("a");
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(<button>Opener</button>);
    expect(screen.getByRole("button", { name: "Opener" })).toHaveFocus();
  });

  it("closes an action sheet with Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <ActionSheet label="Choose" onClose={onClose}>
        <button>One</button>
      </ActionSheet>,
    );

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });
});

describe("Toast", () => {
  it("disappears after a few seconds", async () => {
    vi.useFakeTimers();
    const api = fakeApi();
    api.approvals.mockResolvedValue([approval()]);
    api.resolveApproval.mockResolvedValue(approval({ status: "resolved" }));
    render(
      <StoreProvider
        api={api}
        connect={socketFactory().connect}
        location={{ protocol: "http:", host: "x" }}
      >
        <Inbox onOpenChat={() => undefined} />
        <Toast />
      </StoreProvider>,
    );
    await act(() => vi.advanceTimersByTimeAsync(0));
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByRole("status")).toHaveTextContent("Approved: npm install zod");

    await act(() => vi.advanceTimersByTimeAsync(TOAST_MS));

    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    vi.useRealTimers();
  });
});

describe("an error toast", () => {
  it("stays until it is dismissed", async () => {
    vi.useFakeTimers();
    const api = fakeApi();
    api.approvals.mockResolvedValue([approval()]);
    api.resolveApproval.mockRejectedValue(new Error("Could not reach your Mac"));
    render(
      <StoreProvider
        api={api}
        connect={socketFactory().connect}
        location={{ protocol: "http:", host: "x" }}
      >
        <Inbox onOpenChat={() => undefined} />
        <Toast />
      </StoreProvider>,
    );
    await act(() => vi.advanceTimersByTimeAsync(0));
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await act(() => vi.advanceTimersByTimeAsync(TOAST_MS * 10));

    expect(screen.getByRole("status")).toHaveTextContent("Could not reach your Mac");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    vi.useRealTimers();
  });
});

describe("DiffStats", () => {
  it("handles empty and single-file changes", () => {
    render(<DiffStats additions={0} deletions={0} files={1} />);

    expect(screen.getByText("1 file")).toBeInTheDocument();
  });
});

describe("toolIcon", () => {
  it("falls back to the terminal icon", () => {
    expect(toolIcon("WebFetch")).toBe("term");
    expect(toolIcon("Read")).toBe("file");
  });
});

describe("useStore", () => {
  it("needs a provider", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => renderHook(() => useStore())).toThrow("useStore needs a StoreProvider");
  });
});
