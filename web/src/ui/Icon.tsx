import type { ReactNode } from "react";

// The winged pixie, 12 by 10 pixels, "#" filled.
const PIXIE = [
  "............",
  "....####....",
  "#..######..#",
  "##.#.##.#.##",
  "############",
  "##.######.##",
  "#..######..#",
  "....#..#....",
  "............",
  "............",
];

/** Each row's runs of filled pixels, one rect apiece. */
function pixelRuns(rows: string[]): { x: number; y: number; width: number }[] {
  return rows.flatMap((row, y) =>
    [...row.matchAll(/#+/g)].map((run) => ({ x: run.index, y, width: run[0].length })),
  );
}

// Stroke icons from the locked design (plans/design/iphone.html), drawn on a 24px grid.
const PATHS = {
  plus: <path d="M12 5v14M5 12h14" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M20 20l-4.2-4.2" />
    </>
  ),
  mic: (
    <>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />
    </>
  ),
  clip: (
    <path d="M20 11.5l-8.2 8.2a5 5 0 0 1-7-7l8.6-8.6a3.4 3.4 0 0 1 4.8 4.8l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8" />
  ),
  send: <path d="M12 19V5M6 11l6-6 6 6" />,
  chev: <path d="M6 9l6 6 6-6" />,
  chevl: <path d="M15 6l-6 6 6 6" />,
  chevr: <path d="M9 6l6 6-6 6" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  branch: (
    <>
      <circle cx="6" cy="6" r="2" />
      <circle cx="6" cy="18" r="2" />
      <circle cx="18" cy="8" r="2" />
      <path d="M6 8v8M18 10c0 3.5-4 4-10 6.5" />
    </>
  ),
  folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />,
  file: <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5" />,
  doc: (
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h4" />
  ),
  code: <path d="M8.5 7.5L4 12l4.5 4.5M15.5 7.5L20 12l-4.5 4.5M13.5 5l-3 14" />,
  term: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="3" />
      <path d="M7 9l3 3-3 3M12 15h5" />
    </>
  ),
  edit: <path d="M4 20h4L19 9l-4-4L4 16z" />,
  spark: (
    <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z" />
  ),
  shield: <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z" />,
  // The robot (B86): Agents, and the Task and Agent tools.
  bot: (
    <>
      <rect x="4.5" y="8" width="15" height="11.5" rx="3" />
      <circle cx="12" cy="3.8" r="1.2" />
      <path d="M12 8V5M2.5 12.5v3M21.5 12.5v3M10 16h4" />
      <circle cx="9.3" cy="12.5" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="14.7" cy="12.5" r="1.1" fill="currentColor" stroke="none" />
    </>
  ),
  drive: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2.5" />
      <path d="M3 12.5h18M7 16h6M16.5 16h.01" />
    </>
  ),
  chart: <path d="M4 20h16M7 16.5v-5M12 16.5v-10M17 16.5v-8" />,
  list: (
    <path d="M4 6.5l1.3 1.3 2.5-2.5M4 12.5l1.3 1.3 2.5-2.5M4.8 18h2M11 6.5h9M11 12.5h9M11 18h9" />
  ),
  // Settings > Features (B103): an open book, as the Mac's.
  book: (
    <path d="M12 5.4C9.9 4 6.9 3.6 3 3.9v15c3.9-.3 6.9.1 9 1.5 2.1-1.4 5.1-1.8 9-1.5v-15c-3.9-.3-6.9.1-9 1.5zM12 5.4v15" />
  ),
  // The Chats tab (B102): a list of lines, as the Mac's sidebar.
  lines: <path d="M5 6h14M5 12h14M5 18h9" />,
  q: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9.7 9.6a2.4 2.4 0 1 1 3.3 2.2c-.6.3-1 .8-1 1.5v.4M12 16.6h.01" />
    </>
  ),
  dots: <path d="M6 12h.01M12 12h.01M18 12h.01" strokeWidth="3" />,
  pin: <path d="M9 4h6l-1 6 3 3v2H7v-2l3-3zM12 15v6" />,
  archive: (
    <>
      <rect x="3" y="4" width="18" height="5" rx="1.5" />
      <path d="M5 9v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9M10 13h4" />
    </>
  ),
  trash: <path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" />,
  stop: <rect x="6.5" y="6.5" width="11" height="11" rx="2" />,
  inbox: <path d="M3 13l3-8h12l3 8v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 13h5l1.5 2.5h5L16 13h5" />,
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 20.5a7.5 7.5 0 0 1 15 0" />
    </>
  ),
  gear: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" />
    </>
  ),
  restore: <path d="M4 5v5h5M5.3 15a7.5 7.5 0 1 0 1.6-8.1L4 10" />,
  bell: <path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0" />,
  // The Settings list (B81).
  contrast: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 3.5a8.5 8.5 0 0 0 0 17z" fill="currentColor" />
    </>
  ),
  // The winged pixie (B86), in pixels on its own grid, centred in the box.
  pixie: (
    <svg
      width="24"
      height="24"
      viewBox="-1 -2 14 14"
      fill="currentColor"
      stroke="none"
      shapeRendering="crispEdges"
    >
      {pixelRuns(PIXIE).map(({ x, y, width }) => (
        <rect key={`${String(x)},${String(y)}`} x={x} y={y} width={width} height="1" />
      ))}
    </svg>
  ),
  star: <path d="M12 3l2.6 5.9 6.4.6-4.8 4.3 1.4 6.2L12 16.8 6.4 20l1.4-6.2L3 9.5l6.4-.6z" />,
  devices: (
    <>
      <rect x="2.5" y="4.5" width="13" height="10" rx="1.5" />
      <path d="M1.5 18h15" />
      <rect x="17" y="8" width="5" height="10.5" rx="1.2" />
    </>
  ),
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof PATHS;

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg
      className={className === undefined ? "ic" : `ic ${className}`}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
