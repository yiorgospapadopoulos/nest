import { useBridge } from "../context.ts";

/**
 * Minimise, maximise and close at the tab strip's end (window frame A, B117). Close hides
 * the window to the tray. The strip's empty parts carry data-tauri-drag-region, so Tauri
 * moves the window when they are dragged and maximises it on a double click.
 */
export function WindowButtons() {
  const bridge = useBridge();
  return (
    <div className="dk-wbtns">
      <button className="dk-wbtn" aria-label="Minimise" onClick={() => void bridge.minimize()}>
        <svg viewBox="0 0 10 10" aria-hidden="true">
          <path d="M2 5h6" />
        </svg>
      </button>
      <button
        className="dk-wbtn"
        aria-label="Maximise"
        onClick={() => void bridge.toggleMaximize()}
      >
        <svg viewBox="0 0 10 10" aria-hidden="true">
          <rect x="2" y="2" width="6" height="6" />
        </svg>
      </button>
      <button className="dk-wbtn" aria-label="Close" onClick={() => void bridge.close()}>
        <svg viewBox="0 0 10 10" aria-hidden="true">
          <path d="M2.5 2.5l5 5M7.5 2.5l-5 5" />
        </svg>
      </button>
    </div>
  );
}
