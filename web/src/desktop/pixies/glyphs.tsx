// The Pixies tab's small symbols, drawn after the SF Symbols the Mac's views use, on a
// 16 unit grid with a thin stroke.
import type { ReactNode } from "react";

const PATHS = {
  plus: <path d="M8 3v10M3 8h10" />,
  team: (
    <>
      <circle cx="6" cy="5.6" r="2.3" />
      <path d="M1.8 13c.3-2.4 2-3.8 4.2-3.8s3.9 1.4 4.2 3.8z" />
      <path d="M10.4 3.6a2.2 2.2 0 1 1 .3 4.3M11.6 9.4c1.5.3 2.5 1.6 2.7 3.6h-2.2" />
    </>
  ),
  eye: (
    <>
      <path d="M1.8 8S4 3.8 8 3.8 14.2 8 14.2 8 12 12.2 8 12.2 1.8 8 1.8 8z" />
      <circle cx="8" cy="8" r="2" />
    </>
  ),
  eyeSlash: (
    <>
      <path d="M6.3 4.1A6 6 0 0 1 8 3.8C12 3.8 14.2 8 14.2 8a10 10 0 0 1-1.6 2.2M10 11.8a5.7 5.7 0 0 1-2 .4C4 12.2 1.8 8 1.8 8a10.5 10.5 0 0 1 2.4-2.9" />
      <path d="M2.5 2.5l11 11M6.6 6.6a2 2 0 0 0 2.8 2.8" />
    </>
  ),
  chevronDown: <path d="M4.5 6.2 8 9.7l3.5-3.5" />,
  chevronRight: <path d="M6.2 4.5 9.7 8l-3.5 3.5" />,
  chevronLeft: <path d="M9.8 4.5 6.3 8l3.5 3.5" />,
  upDown: <path d="M5.2 6.3 8 3.5l2.8 2.8M5.2 9.7 8 12.5l2.8-2.8" />,
  more: (
    <>
      <circle cx="3.5" cy="8" r=".95" fill="currentColor" stroke="none" />
      <circle cx="8" cy="8" r=".95" fill="currentColor" stroke="none" />
      <circle cx="12.5" cy="8" r=".95" fill="currentColor" stroke="none" />
    </>
  ),
  close: <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />,
  play: <path d="M5 3.5v9l7.5-4.5z" />,
  clock: (
    <>
      <circle cx="8" cy="8" r="5.6" />
      <path d="M8 4.8V8l2.2 1.4" />
    </>
  ),
  file: (
    <>
      <path d="M4 2.5h5l3 3v8H4z" />
      <path d="M9 2.5v3h3" />
    </>
  ),
  workspace: (
    <>
      <rect x="2" y="3" width="12" height="10" rx="1.6" />
      <path d="M8 3v10" />
    </>
  ),
  agent: <path d="M8 2.2 9.2 6.8 13.8 8 9.2 9.2 8 13.8 6.8 9.2 2.2 8l4.6-1.2z" />,
} satisfies Record<string, ReactNode>;

export type PxGlyphName = keyof typeof PATHS;

export function PxGlyph({ name, className }: { name: PxGlyphName; className?: string }) {
  return (
    <svg
      className={className === undefined ? "pxg" : `pxg ${className}`}
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
