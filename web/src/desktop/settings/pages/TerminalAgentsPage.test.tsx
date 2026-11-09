// Settings > Terminal agents (B151) on the desktop: switching a client on starts it at
// Read only, its level changes from the menu, and a refused switch leaves it off.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { ApiError } from "../../../api/client.ts";
import type { OutsideClient } from "../../../api/types.ts";
import { fakeApi, type FakeApi } from "../../../test/fakeApi.ts";
import { socketFactory } from "../../../test/fakeSocket.ts";
import { memoryStorage } from "../../../test/render.tsx";
import { browserBridge } from "../../bridge.ts";
import { DesktopApp } from "../../DesktopApp.tsx";

const NEST = "/Users/me/.local/bin/nest";

function client(kind: OutsideClient["kind"], label: string, fields: Partial<OutsideClient> = {}) {
  const command = kind === "shell" ? [NEST] : [NEST, "mcp", "--client", kind];
  return {
    kind,
    label,
    on: false,
    access: null,
    turned_on_at: null,
    last_seen_at: null,
    command,
    ...fields,
  } satisfies OutsideClient;
}

const CLIENTS: OutsideClient[] = [
  client("claude_code", "Claude Code"),
  client("codex", "Codex"),
  client("other", "Other MCP apps", { on: true, access: "read" }),
  client("shell", "nest command"),
];

beforeAll(() => {
  // jsdom has none; the desktop workspace measures itself with one.
  globalThis.ResizeObserver = class {
    observe() {
      return undefined;
    }
    unobserve() {
      return undefined;
    }
    disconnect() {
      return undefined;
    }
  };
});

async function openPage(api: FakeApi) {
  const storage = memoryStorage();
  render(
    <DesktopApp
      bridge={browserBridge({ search: "" }, null)}
      api={api}
      connect={socketFactory().connect}
      location={{ protocol: "http:", host: "127.0.0.1:8765" }}
      storage={() => storage}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
  const pages = screen.getByRole("navigation", { name: "Settings pages" });
  fireEvent.click(within(pages).getByRole("button", { name: "Terminal agents" }));
  await screen.findByRole("switch", { name: "Claude Code" });
}

describe("Settings > Terminal agents (B151)", () => {
  it("switches a client on at Read only, then changes its level", async () => {
    const api = fakeApi();
    api.outsideClients.mockResolvedValue(CLIENTS);
    api.turnOnOutsideClient.mockImplementation((kind, access) =>
      Promise.resolve(client(kind, "Claude Code", { on: true, access })),
    );
    await openPage(api);

    fireEvent.click(screen.getByRole("switch", { name: "Claude Code" }));
    expect(api.turnOnOutsideClient).toHaveBeenLastCalledWith("claude_code", "read");
    const level = await screen.findByRole("button", { name: "Claude Code access: Read only" });
    fireEvent.click(level);
    fireEvent.click(await screen.findByRole("menuitemcheckbox", { name: "Full" }));
    expect(api.turnOnOutsideClient).toHaveBeenLastCalledWith("claude_code", "full");
    expect(
      await screen.findByRole("button", { name: "Claude Code access: Full" }),
    ).toBeInTheDocument();
  });

  it("shows the line to give another app, and leaves a refused client off", async () => {
    const api = fakeApi();
    api.outsideClients.mockResolvedValue(CLIENTS);
    api.turnOnOutsideClient.mockRejectedValue(new ApiError(502, "Codex was not found."));
    await openPage(api);

    expect(screen.getByText(`${NEST} mcp --client other`)).toBeInTheDocument();
    const codex = screen.getByRole("switch", { name: "Codex" });
    fireEvent.click(codex);
    await waitFor(() => {
      expect(api.turnOnOutsideClient).toHaveBeenCalledWith("codex", "read");
    });
    expect(await screen.findByText(/Codex was not found/)).toBeInTheDocument();
    expect(codex).not.toBeChecked();
  });
});
