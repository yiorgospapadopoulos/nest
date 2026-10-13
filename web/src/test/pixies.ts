import { screen } from "@testing-library/react";
import type { Pixie } from "../api/types.ts";
import { fakeApi, type FakeApi } from "./fakeApi.ts";
import { pixie } from "./fixtures.ts";
import { renderApp } from "./render.tsx";

/** The app with one pixie, its page open on the Chat or Details tab. */
export async function openPixie(
  api: FakeApi = fakeApi(),
  shown: Pixie = pixie(),
  tab: "Chat" | "Details" = "Chat",
) {
  api.pixies.mockResolvedValue([shown]);
  api.updatePixie.mockImplementation((_id, body) => Promise.resolve({ ...shown, ...body }));
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${shown.name},`) }));
  if (tab === "Details") await rendered.user.click(screen.getByRole("tab", { name: "Details" }));
  return rendered;
}
