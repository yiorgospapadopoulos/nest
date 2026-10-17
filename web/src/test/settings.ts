import { screen } from "@testing-library/react";
import { renderApp } from "./render.tsx";

/** The app on the Settings tab, with the page named `page` open (a category or a project). */
export async function openSettings(
  page: string | null,
  options: Parameters<typeof renderApp>[0] = {},
) {
  const rendered = await renderApp(options);
  await rendered.user.click(screen.getByRole("tab", { name: "Settings" }));
  if (page !== null) await rendered.user.click(await screen.findByRole("button", { name: page }));
  return rendered;
}
