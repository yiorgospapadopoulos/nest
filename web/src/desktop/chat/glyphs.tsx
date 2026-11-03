// The chat pane's small symbols, drawn after the SF Symbols the Mac's chat uses, on a
// 16 unit grid with a thin stroke.
import type { ReactNode } from "react";

const PATHS = {
  chevron: <path d="M4.5 6.2 8 9.7l3.5-3.5" />,
  chevronUp: <path d="M4.5 9.8 8 6.3l3.5 3.5" />,
  copy: (
    <>
      <rect x="5.5" y="5.5" width="7.5" height="8" rx="1.6" />
      <path d="M10.5 5.5V3.6c0-.6-.5-1.1-1.1-1.1H4.1c-.6 0-1.1.5-1.1 1.1v6.3c0 .6.5 1.1 1.1 1.1h1.4" />
    </>
  ),
  more: (
    <>
      <circle cx="3.5" cy="8" r=".9" fill="currentColor" stroke="none" />
      <circle cx="8" cy="8" r=".9" fill="currentColor" stroke="none" />
      <circle cx="12.5" cy="8" r=".9" fill="currentColor" stroke="none" />
    </>
  ),
  edit: <path d="M10.6 2.9 13 5.3l-7.6 7.6-3 .6.6-3zM9.4 4.1l2.4 2.4" />,
  rewind: <path d="M3 4v3.3h3.3M3.3 7.2A5 5 0 1 1 4.6 11" />,
  fork: (
    <>
      <circle cx="4.5" cy="3.5" r="1.4" />
      <circle cx="11.5" cy="3.5" r="1.4" />
      <circle cx="8" cy="12.5" r="1.4" />
      <path d="M4.5 4.9v1.2c0 1.1.9 2 2 2h3c1.1 0 2-.9 2-2V4.9M8 8.1v3" />
    </>
  ),
  terminal: (
    <>
      <rect x="2" y="3" width="12" height="10" rx="1.8" />
      <path d="m4.8 6.3 2 1.7-2 1.7M8.4 10.2h2.8" />
    </>
  ),
  doc: (
    <>
      <path d="M4 2.5h5l3 3v8H4z" />
      <path d="M9 2.5v3h3M6 8.5h4M6 10.8h4" />
    </>
  ),
  pencil: <path d="M10.6 2.9 13 5.3l-7.6 7.6-3 .6.6-3z" />,
  search: (
    <>
      <circle cx="7" cy="7" r="4" />
      <path d="m10 10 3.3 3.3" />
    </>
  ),
  globe: (
    <>
      <circle cx="8" cy="8" r="5.6" />
      <path d="M2.4 8h11.2M8 2.4c1.7 1.6 2.4 3.6 2.4 5.6s-.7 4-2.4 5.6C6.3 12 5.6 10 5.6 8s.7-4 2.4-5.6" />
    </>
  ),
  agent: (
    <>
      <path d="M8 2.2 9.2 6.8 13.8 8 9.2 9.2 8 13.8 6.8 9.2 2.2 8l4.6-1.2z" />
    </>
  ),
  wrench: (
    <path d="M10.9 2.6a3 3 0 0 0-3.4 4L2.9 11.2a1.3 1.3 0 0 0 1.9 1.9l4.6-4.6a3 3 0 0 0 4-3.4l-1.8 1.8-1.7-.4-.4-1.7z" />
  ),
  hook: <path d="M8 2.5v6.3a2.7 2.7 0 1 1-5.4 0V7.6M8 2.5 6.3 4.2M8 2.5l1.7 1.7" />,
  check: <path d="m3.3 8.4 3 3 6.4-6.6" />,
  warning: (
    <>
      <path d="M8 2.4 14 13H2z" />
      <path d="M8 6.5v3M8 11.2v.1" />
    </>
  ),
  plus: <path d="M8 3v10M3 8h10" />,
  send: <path d="M8 13V3.5M3.8 7.6 8 3.4l4.2 4.2" />,
  stop: <rect x="4" y="4" width="8" height="8" rx="1.2" fill="currentColor" stroke="none" />,
  branch: (
    <>
      <circle cx="4.5" cy="3.5" r="1.3" />
      <circle cx="4.5" cy="12.5" r="1.3" />
      <circle cx="11.5" cy="5" r="1.3" />
      <path d="M4.5 4.8v6.4M11.5 6.3c0 3-3.5 2.5-6.3 5" />
    </>
  ),
  diff: (
    <>
      <path d="M5 2.5v5M2.5 5h5M2.5 12h5" />
      <path d="M10.5 3.5h3v9h-3" />
    </>
  ),
  attach: (
    <path d="m12.6 7.6-4.8 4.8a3 3 0 0 1-4.2-4.2l5.1-5.1a2 2 0 0 1 2.8 2.8l-5 5a1 1 0 0 1-1.4-1.4l4.6-4.6" />
  ),
  pause: (
    <>
      <circle cx="8" cy="8" r="5.8" />
      <path d="M6.6 5.8v4.4M9.4 5.8v4.4" />
    </>
  ),
  play: <path d="M5 3.3v9.4l7.4-4.7z" fill="currentColor" />,
  playCircle: (
    <>
      <circle cx="8" cy="8" r="5.8" />
      <path d="M6.8 5.8v4.4l3.4-2.2z" fill="currentColor" stroke="none" />
    </>
  ),
  checkCircle: (
    <>
      <circle cx="8" cy="8" r="5.8" />
      <path d="m5.6 8.2 1.7 1.7 3.2-3.4" />
    </>
  ),
  stopCircle: (
    <>
      <circle cx="8" cy="8" r="5.8" />
      <rect x="6" y="6" width="4" height="4" rx=".6" fill="currentColor" stroke="none" />
    </>
  ),
  alertCircle: (
    <>
      <circle cx="8" cy="8" r="5.8" />
      <path d="M8 5v3.4M8 10.8v.1" />
    </>
  ),
  refresh: <path d="M13 3.5V7H9.5M12.7 6.8A5 5 0 1 0 12.6 10" />,
  close: <path d="m4 4 8 8M12 4l-8 8" />,
  maximize: <path d="M9.5 2.5h4v4M6.5 13.5h-4v-4M13.5 2.5 9.3 6.7M2.5 13.5l4.2-4.2" />,
  restore: <path d="M2.8 6.6h3.8V2.8M13.2 9.4H9.4v3.8M6.6 6.6 2.5 2.5M9.4 9.4l4.1 4.1" />,
  file: <path d="M4 2.5h5l3 3v8H4zM9 2.5v3h3" />,
  pr: (
    <>
      <circle cx="4.5" cy="3.5" r="1.3" />
      <circle cx="4.5" cy="12.5" r="1.3" />
      <circle cx="11.5" cy="12.5" r="1.3" />
      <path d="M4.5 4.8v6.4M11.5 11.2V6.5c0-1.1-.9-2-2-2H7.5M9 3l-1.5 1.5L9 6" />
    </>
  ),
  issue: (
    <>
      <circle cx="8" cy="8" r="5.6" />
      <circle cx="8" cy="8" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  machine: (
    <>
      <rect x="2" y="3" width="12" height="8" rx="1.3" />
      <path d="M5.5 13.5h5M8 11v2.5" />
    </>
  ),
  checklist: <path d="m2.5 4.5 1.2 1.2 2-2.2M2.5 10.5l1.2 1.2 2-2.2M8 5h5.5M8 11h5.5" />,
  bell: <path d="M4 11.5V7.3a4 4 0 0 1 8 0v4.2l1.2 1.3H2.8zM6.6 13.8a1.5 1.5 0 0 0 2.8 0" />,
  repeat: (
    <path d="M3 7V6a2 2 0 0 1 2-2h7.5M10.5 2l2 2-2 2M13 9v1a2 2 0 0 1-2 2H3.5M5.5 14l-2-2 2-2" />
  ),
  arrowDown: <path d="M8 3v9.5M3.8 8.4 8 12.6l4.2-4.2" />,
  open: (
    <path d="M9 2.5h4.5V7M13.3 2.7 7.5 8.5M11.5 9.5v3.2c0 .5-.4.8-.8.8H3.3c-.4 0-.8-.3-.8-.8V5.3c0-.4.4-.8.8-.8h3.2" />
  ),
  spark: <path d="M8 2v3M8 11v3M2 8h3M11 8h3M4 4l2 2M10 10l2 2M12 4l-2 2M6 10l-2 2" />,
} satisfies Record<string, ReactNode>;

export type GlyphName = keyof typeof PATHS;

/** A symbol at `size` pixels; decorative unless the button around it names itself. */
export function Glyph({
  name,
  size = 12,
  className,
}: {
  name: GlyphName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      className={className === undefined ? "dc-g" : `dc-g ${className}`}
      viewBox="0 0 16 16"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}

/** The chevron of a row that opens in place: pointing right while closed, down open. */
export function Disclosure({ open }: { open: boolean }) {
  return <Glyph name="chevron" size={9} className={open ? "dc-disc open" : "dc-disc"} />;
}
