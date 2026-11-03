// How the tab strip fits the window (TabStrip.swift): the usage meter, search and window
// buttons keep their size and always show; the project tabs, all of one width, shrink from
// 180 down to 56 to make room, as wide as on the Mac. The pill's gap is kept only while the
// tabs fit left of it at that same width and the right cluster fits right of it; otherwise
// the pill simply covers the strip. Below the smallest width the tabs scroll, the Pixies
// and General tabs staying put; the current tab keeps room for its name all along.
import type { StripGap } from "./pillGap.ts";

export const TAB_MAX = 180;
export const TAB_MIN = 56;
// The current tab's least width: its icon, a readable name, its count and close button.
export const CURRENT_MIN = 132;
// Below this a tab's parts sit closer, so its count still fits (frame.css .narrow).
export const TAB_NARROW = 84;
// Between two tabs.
export const TAB_SPACING = 2;
// The least room between the tabs' side and the right cluster (Spacer(minLength: 12)).
const SPACER = 12;

export interface StripFitInput {
  // The strip's width: the window's.
  width: number;
  // Where the pill covers the strip, or null.
  gap: StripGap | null;
  // How many project tabs are open.
  tabs: number;
  // Everything on the left but the project tabs: the strip's padding, the Pixies tab, the
  // divider, the + and the space between them.
  lead: number;
  // The right cluster with the strip's padding: usage, search and window buttons.
  trail: number;
}

export interface StripFit {
  // Each project tab's width but the current one's.
  tabWidth: number;
  // The current project tab's width: the others' while that leaves its name readable.
  currentWidth: number;
  // Whether the strip keeps clear of the pill.
  keepsGap: boolean;
  // The tabs need more room than there is, even at their smallest: they scroll.
  overflows: boolean;
}

/** Each tab's width when `count` tabs share `room`. */
function share(room: number, count: number): number {
  return (room - TAB_SPACING * (count - 1)) / count;
}

const clamp = (width: number) => Math.floor(Math.min(TAB_MAX, Math.max(TAB_MIN, width)));

export function stripFit({ width, gap, tabs, lead, trail }: StripFitInput): StripFit {
  if (tabs <= 0) {
    return { tabWidth: TAB_MAX, currentWidth: TAB_MAX, keepsGap: gap !== null, overflows: false };
  }
  // The Mac's width: the tabs share the strip with nothing but the right cluster.
  const free = width - lead - trail - SPACER;
  const room = share(free, tabs);
  const mac = clamp(room);
  // Keeping clear of the pill never makes the tabs narrower than that (wave 7: at the
  // smallest window the current tab kept only its icon, count and close button).
  const keepsGap = gap !== null && trail <= gap.right && clamp(share(gap.left - lead, tabs)) >= mac;
  if (mac >= CURRENT_MIN || tabs === 1) {
    return { tabWidth: mac, currentWidth: mac, keepsGap, overflows: room < TAB_MIN };
  }
  // Too narrow for a name: the current tab keeps its least width, the others share the rest.
  const others = share(free - CURRENT_MIN - TAB_SPACING, tabs - 1);
  return {
    tabWidth: clamp(others),
    currentWidth: CURRENT_MIN,
    keepsGap: false,
    overflows: others < TAB_MIN,
  };
}
