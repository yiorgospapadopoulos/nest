import type { CSSProperties } from "react";

/**
 * The working animation (B80): three accent dots drifting in a 4:3 box `size` pixels tall,
 * held still under Reduce Motion. Hidden from assistive technology unless given a label.
 */
export function Fireflies({ size = 12, label }: { size?: number; label?: string }) {
  return (
    <span
      className="ff"
      style={{ "--ffh": `${String(size)}px` } as CSSProperties}
      {...(label === undefined
        ? { "aria-hidden": true }
        : { role: "img", "aria-label": label, title: label })}
    >
      <i />
      <i />
      <i />
    </span>
  );
}
