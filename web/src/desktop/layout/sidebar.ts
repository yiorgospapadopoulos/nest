// The left sidebar's width, which the user drags (B45), ported from SidebarWidth.swift: one
// width for the chats sidebar and the Pixies list, kept on this device.
import { MINIMUM_PANE_WIDTH } from "./workspace.ts";

export const SIDEBAR_STANDARD = 236;
export const SIDEBAR_MINIMUM = 200;
export const SIDEBAR_MAXIMUM = 420;
export const SIDEBAR_STEP = 10;
// A collapsed side panel becomes a rail of status dots this wide.
export const RAIL_WIDTH = 20;
export const RIGHT_PANEL_WIDTH = 320;

/**
 * `proposed` within the bounds, leaving the workspace room for one pane of `available`,
 * the width the sidebar and the workspace share; before the window is measured (0) only
 * the fixed bounds apply. The minimum wins in a window too narrow for both.
 */
export function clampSidebar(proposed: number, available: number): number {
  const upper =
    available > 0 ? Math.min(SIDEBAR_MAXIMUM, available - MINIMUM_PANE_WIDTH) : SIDEBAR_MAXIMUM;
  return Math.max(SIDEBAR_MINIMUM, Math.min(proposed, upper));
}

/** A saved width within the fixed bounds; the standard one when missing or unreadable. */
export function storedSidebar(text: string | null): number {
  const width = text === null ? NaN : Number(text);
  return Number.isFinite(width) && text?.trim() !== "" ? clampSidebar(width, 0) : SIDEBAR_STANDARD;
}
