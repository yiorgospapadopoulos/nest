// The size a chat compacts at by itself (B146), chosen from the context meter's menu.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Session } from "../../api/types.ts";
import { StoreProvider } from "../../store/StoreProvider.tsx";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { acpProvider, claudeProvider, pixie, session } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { Composer } from "./Composer.tsx";

const context = { percent: 41, used: 82_000, limit: 200_000 };

function renderChat(api: FakeApi, chat: Session) {
  const storage = memoryStorage();
  render(
    <StoreProvider
      api={api}
      connect={socketFactory().connect}
      storage={() => storage}
      location={{ protocol: "http:", host: "127.0.0.1:8765" }}
    >
      <Composer
        target={
          chat.pixie_id === null
            ? { kind: "chat", session: chat }
            : { kind: "pixie", pixie: chat.pixie_id, session: chat }
        }
      />
    </StoreProvider>,
  );
}

function openContextMenu() {
  fireEvent.pointerDown(screen.getByRole("button", { name: "Context 41 percent" }), {
    button: 0,
  });
}

async function chooseSize(current: string, size: string) {
  openContextMenu();
  fireEvent.click(screen.getByRole("menuitem", { name: `Compact at: ${current}` }));
  fireEvent.click(await screen.findByRole("menuitemcheckbox", { name: size }));
}

describe("Compact at", () => {
  it("sets a chat's size, and Auto gives it back to the engine", async () => {
    const api = fakeApi();
    renderChat(api, session({ context }));
    await chooseSize("Auto", "300k");
    expect(api.updateSession).toHaveBeenCalledWith("s1", { compact_at: 300_000 });

    await chooseSize("Auto", "Auto");
    expect(api.updateSession).toHaveBeenLastCalledWith("s1", { compact_at: "auto" });
  });

  it("changes a pixie's own chat through its pixie", async () => {
    const api = fakeApi();
    api.pixies.mockResolvedValue([pixie({ compact_at: 400_000, chat_session_id: "s1" })]);
    renderChat(api, session({ context, pixie_id: "p1", compact_at: 400_000 }));
    await waitFor(() => {
      expect(api.pixies).toHaveBeenCalled();
    });

    await chooseSize("400k", "1M");
    expect(api.updatePixie).toHaveBeenCalledWith("p1", { compact_at: 1_000_000 });
    expect(api.updateSession).not.toHaveBeenCalled();
  });

  it("is not offered on an engine that compacts its own way", async () => {
    const api = fakeApi();
    api.providers.mockResolvedValue({ providers: [claudeProvider(), acpProvider()] });
    renderChat(api, session({ context, provider: "opencode" }));
    await waitFor(() => {
      expect(api.providers).toHaveBeenCalled();
    });
    // The engines list arrives after the first render.
    await new Promise((done) => setTimeout(done, 0));

    openContextMenu();
    expect(screen.getByRole("menuitem", { name: "Compact" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /^Compact at/ })).not.toBeInTheDocument();
  });
});
