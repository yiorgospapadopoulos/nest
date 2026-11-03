// A note goes after 3 seconds whatever its kind, as the Mac's Shell.show; an error no
// longer waits to be dismissed over the tab strip.
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Actions } from "../../store/actions.ts";
import { StoreContext } from "../../store/context.ts";
import { initialState } from "../../store/state.ts";
import { DESKTOP_TOAST_MS, DesktopToast } from "./Toast.tsx";

afterEach(() => {
  vi.useRealTimers();
});

describe("the desktop's toast", () => {
  it("goes after 3 seconds, an error too, and offers nothing to click", () => {
    vi.useFakeTimers();
    const dismissToast = vi.fn();
    render(
      <StoreContext
        value={{
          state: { ...initialState, toast: { id: 1, text: "Could not save", tone: "error" } },
          actions: { dismissToast } as unknown as Actions,
          address: "127.0.0.1:8765",
        }}
      >
        <DesktopToast />
      </StoreContext>,
    );
    expect(screen.getByText("Could not save")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    act(() => {
      vi.advanceTimersByTime(DESKTOP_TOAST_MS - 1);
    });
    expect(dismissToast).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(dismissToast).toHaveBeenCalledTimes(1);
  });
});
