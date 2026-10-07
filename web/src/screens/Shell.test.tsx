import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { NAVIGATE } from "../pwa/navigate.ts";
import { fakeApi } from "../test/fakeApi.ts";
import { installBrowserPush, uninstallBrowserPush } from "../test/fakePush.ts";
import { detail, session } from "../test/fixtures.ts";
import { renderApp } from "../test/render.tsx";

afterEach(() => {
  uninstallBrowserPush();
});

function apiWithChat() {
  const chat = session({ id: "s/1", title: "Fix login" });
  const api = fakeApi();
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  return api;
}

describe("deep links", () => {
  it("opens a chat from its address and goes back to the projects tab", async () => {
    window.history.replaceState(null, "", "/chat/s%2F1");
    const { user } = await renderApp({ api: apiWithChat(), ready: false });

    expect(await screen.findByRole("region", { name: "Fix login" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/chat/s%2F1");
    await user.click(screen.getByRole("button", { name: /back/i }));

    expect(screen.getByRole("tab", { name: "Projects" })).toHaveAttribute("aria-selected", "true");
    expect(window.location.pathname).toBe("/projects");
  });

  it("opens a tab from its address and keeps the address current", async () => {
    window.history.replaceState(null, "", "/account");
    const { user } = await renderApp();

    expect(screen.getByRole("heading", { level: 1, name: "Account" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Inbox" }));
    expect(window.location.pathname).toBe("/inbox");
  });

  it("follows a tapped notification in an app that is already open", async () => {
    const { worker } = installBrowserPush();
    await renderApp({ api: apiWithChat() });
    const send = (data: unknown) => {
      act(() => {
        worker.dispatchEvent(new MessageEvent("message", { data }));
      });
    };

    send({ type: NAVIGATE, url: "/chat/s%2F1" });
    expect(await screen.findByRole("region", { name: "Fix login" })).toBeInTheDocument();

    send({ type: "other", url: "/account" });
    send(null);
    expect(screen.getByRole("region", { name: "Fix login" })).toBeInTheDocument();

    send({ type: NAVIGATE, url: "/inbox" });
    expect(screen.getByRole("heading", { level: 1, name: "Inbox" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/inbox");
  });
});
