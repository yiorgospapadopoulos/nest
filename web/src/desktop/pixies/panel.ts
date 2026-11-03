// The pages of the Pixies tab's right panel (PixieDetails.swift's PixiePanel): the
// details, or a page opened from them in place, each with a way back.

export type PixiePage =
  | { page: "details" }
  | { page: "soul" }
  | { page: "memory" }
  | { page: "activity" }
  | { page: "habits" }
  // A note of the pixie's memory, by its name.
  | { page: "note"; note: string }
  // New habit (null) or Edit.
  | { page: "habit"; habit: string | null }
  | { page: "history"; habit: string };

export const DETAILS: PixiePage = { page: "details" };

/** The page its back button returns to, and the button's word; none from the details. */
export function backOf(page: PixiePage): { page: PixiePage; label: string } | null {
  switch (page.page) {
    case "details":
      return null;
    case "note":
      return { page: { page: "memory" }, label: "Memory" };
    case "habit":
    case "history":
      return { page: { page: "habits" }, label: "Habits" };
    default:
      return { page: DETAILS, label: "Details" };
  }
}

/** The page opened and the pixie it was opened for. */
export interface PanelState {
  pixie: string;
  page: PixiePage;
}

/** The page the panel shows for the focused pixie: another pixie's focus brings the details. */
export function shownPage(state: PanelState, pixie: string): PixiePage {
  return state.pixie === pixie ? state.page : DETAILS;
}
