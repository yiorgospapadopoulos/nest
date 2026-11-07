import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { StoreContext, type StoreValue } from "../../store/context.ts";
import { browserBridge, type Bridge } from "../bridge.ts";
import { BridgeContext } from "../context.ts";
import { useAppSwap } from "./useAppSwap.ts";

function store(version: string): StoreValue {
  const app_file = { version, path: `/data/daemon/${version}/app-file` };
  return { state: { updates: { status: { app_file } } } } as unknown as StoreValue;
}

function rig() {
  const swapped: string[] = [];
  const bridge: Bridge = {
    ...browserBridge({ search: "" }, null),
    appVersion: () => Promise.resolve("1.0.0"),
    swapApp: (path) => {
      swapped.push(path);
      return Promise.resolve();
    },
  };
  let value = store("1.0.0");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <BridgeContext value={bridge}>
      <StoreContext value={value}>{children}</StoreContext>
    </BridgeContext>
  );
  const hook = renderHook(useAppSwap, { wrapper });
  return {
    swapped,
    move: (version: string) => {
      value = store(version);
      hook.rerender();
    },
  };
}

describe("following the daemon's version", () => {
  it("swaps when the daemon moves while the app stays open", async () => {
    // Regression: the first connect, at the app's own version, used up the launch's one try.
    const { swapped, move } = rig();

    move("2.0.0");

    await waitFor(() => {
      expect(swapped).toEqual(["/data/daemon/2.0.0/app-file"]);
    });
  });

  it("tries only once a launch", async () => {
    const { swapped, move } = rig();

    move("2.0.0");
    await waitFor(() => {
      expect(swapped).toHaveLength(1);
    });
    move("3.0.0");
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(swapped).toHaveLength(1);
  });
});
