import { screen } from "@testing-library/react";
import { SETTINGS_PAGES } from "../routes.ts";
import { renderApp } from "./render.tsx";

/** The address of the Settings page named `page`: a category, else a project. */
function settingsPath(page: string): string {
  const id = SETTINGS_PAGES.find((name) => name === page.toLowerCase());
  return id === undefined ? `/settings/projects/${encodeURIComponent(page)}` : `/settings/${id}`;
}

/**
 * The app on the Settings tab, with the page named `page` open (a category or a project).
 * It starts at the page's address; tests that pass null click through the list.
 */
export async function openSettings(
  page: string | null,
  options: Parameters<typeof renderApp>[0] = {},
) {
  window.history.replaceState(null, "", page === null ? "/settings" : settingsPath(page));
  const rendered = await renderApp(options);
  if (page !== null) await screen.findByRole("button", { name: "Back to Settings" });
  return rendered;
}
