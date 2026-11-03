import { createContext, type ReactNode } from "react";

/**
 * A workspace pane's own controls in place of Back (the desktop app, B117): `lead` before
 * the name, such as the drag handle, and `trail` after the tools, such as maximise and
 * close. Without it the frame is the phone's pushed screen.
 */
export const FrameChrome = createContext<{ lead: ReactNode; trail: ReactNode } | null>(null);
