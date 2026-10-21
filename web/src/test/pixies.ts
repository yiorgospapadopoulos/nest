import { screen } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import type { Pixie } from "../api/types.ts";
import { fakeApi, type FakeApi } from "./fakeApi.ts";
import { pixie } from "./fixtures.ts";
import { renderApp } from "./render.tsx";

/** The Chats tab showing the pixies, chosen from its project menu (B102). */
export async function showPixies(user: UserEvent) {
  await user.click(screen.getByRole("tab", { name: "Chats" }));
  await user.click(screen.getByRole("button", { name: /^Project: / }));
  await user.click(screen.getByRole("menuitemradio", { name: "Pixies" }));
}

/** The app with one pixie, its page open on the Chat or Details tab. */
export async function openPixie(
  api: FakeApi = fakeApi(),
  shown: Pixie = pixie(),
  tab: "Chat" | "Details" = "Chat",
) {
  api.pixies.mockResolvedValue([shown]);
  api.updatePixie.mockImplementation((_id, body) => Promise.resolve({ ...shown, ...body }));
  const rendered = await renderApp({ api });
  await showPixies(rendered.user);
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${shown.name},`) }));
  if (tab === "Details") await rendered.user.click(screen.getByRole("tab", { name: "Details" }));
  return rendered;
}
