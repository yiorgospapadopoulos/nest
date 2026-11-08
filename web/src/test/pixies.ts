import { screen, waitFor } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import { expect } from "vitest";
import type { Pixie } from "../api/types.ts";
import { fakeApi, type FakeApi } from "./fakeApi.ts";
import { applied, pixie } from "./fixtures.ts";
import { renderApp } from "./render.tsx";

/** The Chats tab showing the pixies, chosen from its project menu (B102). */
export async function showPixies(user: UserEvent) {
  await user.click(screen.getByRole("tab", { name: "Chats" }));
  await user.click(screen.getByRole("button", { name: /^Project: / }));
  await user.click(screen.getByRole("menuitemradio", { name: "Pixies" }));
}

/**
 * The app with one pixie, its page open on the Chat or Details tab. It starts at the
 * pixie's address, or with `from: "list"` opens it from the pixies, where going back lands.
 */
export async function openPixie(
  api: FakeApi = fakeApi(),
  shown: Pixie = pixie(),
  tab: "Chat" | "Details" = "Chat",
  { from = "address" }: { from?: "address" | "list" } = {},
) {
  api.pixies.mockResolvedValue([shown]);
  api.updatePixie.mockImplementation((_id, body) =>
    Promise.resolve({ ...shown, ...applied(body) }),
  );
  let rendered;
  if (from === "list") {
    rendered = await renderApp({ api });
    await showPixies(rendered.user);
    await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${shown.name},`) }));
  } else {
    window.history.replaceState(null, "", `/pixie/${encodeURIComponent(shown.id)}`);
    // The tab bar sits under the page, so wait for the page and the event socket instead.
    rendered = await renderApp({ api, ready: false });
    await screen.findByRole("tablist", { name: `${shown.name} sections` });
    const { sockets } = rendered;
    await waitFor(() => {
      expect(sockets.sockets).not.toHaveLength(0);
    });
  }
  if (tab === "Details") await rendered.user.click(screen.getByRole("tab", { name: "Details" }));
  return rendered;
}
