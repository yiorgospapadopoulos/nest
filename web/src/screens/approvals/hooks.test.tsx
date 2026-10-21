import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import type { SessionDiff } from "../../api/types.ts";
import { StoreProvider } from "../../store/StoreProvider.tsx";
import { fakeApi } from "../../test/fakeApi.ts";
import { diff, review, session } from "../../test/fixtures.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { useReview } from "./hooks.ts";

describe("useReview", () => {
  it("publishes nothing until the changes the user reviews have loaded", async () => {
    const api = fakeApi();
    let finish: (value: SessionDiff) => void = () => undefined;
    api.diff.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const wrapper = ({ children }: { children: ReactNode }) => (
      <StoreProvider
        api={api}
        connect={socketFactory().connect}
        location={{ protocol: "http:", host: "x" }}
      >
        {children}
      </StoreProvider>
    );
    // The same approval and chat on every render, as the store hands them out.
    const item = review();
    const chat = session();
    const { result } = renderHook(() => useReview(item, chat), { wrapper });

    // Every screen disables Approve until then; the hook holds to it on its own as well.
    expect(result.current.ready).toBe(false);
    await act(() => result.current.approve("Ship it"));
    expect(api.approve).not.toHaveBeenCalled();

    await act(async () => {
      finish(diff());
      await Promise.resolve();
    });
    expect(result.current.ready).toBe(true);
    await act(() => result.current.approve("Ship it"));
    expect(api.approve).toHaveBeenCalledWith(
      "s1",
      expect.objectContaining({ commit_message: "Ship it" }),
    );
  });
});
