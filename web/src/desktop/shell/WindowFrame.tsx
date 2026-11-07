import type { ReactNode } from "react";
import { WindowButtons } from "./WindowButtons.tsx";

/** The window while no shell shows: an empty strip to move it by, and its buttons. */
export function WindowFrame({ children }: { children: ReactNode }) {
  return (
    <div className="dk-notice">
      <div className="dk-tabs" data-tauri-drag-region>
        <span className="grow" data-tauri-drag-region />
        <WindowButtons />
      </div>
      {children}
    </div>
  );
}
