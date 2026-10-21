import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fakeApi } from "../test/fakeApi.ts";
import { socketFactory } from "../test/fakeSocket.ts";
import { memoryStorage } from "../test/render.tsx";
import { useStore } from "./context.ts";
import { USAGE_BAR_HIDDEN_KEY } from "./devicePrefs.ts";
import { StoreProvider } from "./StoreProvider.tsx";

function Hidden() {
  const { state } = useStore();
  return <p>Hidden: {state.usageBarHidden.join(", ")}</p>;
}

describe("the usage bar's engines (B102 item 29)", () => {
  it("start as this device left them", async () => {
    const storage = memoryStorage();
    storage.setItem(USAGE_BAR_HIDDEN_KEY, JSON.stringify(["codex"]));
    render(
      <StoreProvider api={fakeApi()} connect={socketFactory().connect} storage={() => storage}>
        <Hidden />
      </StoreProvider>,
    );
    expect(await screen.findByText("Hidden: codex")).toBeInTheDocument();
  });
});
