// The symbols the Mac's menus show beside their items (Label(_, systemImage:)), drawn after
// those SF Symbols as thin strokes on a 16 unit grid, like the chat's glyphs.
import type { ReactNode } from "react";

const PATHS = {
  plus: <path d="M8 3v10M3 8h10" />,
  // terminal
  terminal: (
    <>
      <rect x="2" y="3" width="12" height="10" rx="1.8" />
      <path d="m4.8 6.3 2 1.7-2 1.7M8.4 10.2h2.8" />
    </>
  ),
  // globe
  globe: (
    <>
      <circle cx="8" cy="8" r="5.6" />
      <path d="M2.4 8h11.2M8 2.4c1.7 1.6 2.4 3.6 2.4 5.6s-.7 4-2.4 5.6C6.3 12 5.6 10 5.6 8s.7-4 2.4-5.6" />
    </>
  ),
  // chevron.left.forwardslash.chevron.right
  code: <path d="M5 4.5 1.8 8 5 11.5M11 4.5 14.2 8 11 11.5M9.3 3.2 6.7 12.8" />,
  // folder
  folder: (
    <path d="M2.2 4.6c0-.7.5-1.2 1.2-1.2h2.9l1.4 1.5h4.9c.7 0 1.2.5 1.2 1.2v5.8c0 .7-.5 1.2-1.2 1.2H3.4c-.7 0-1.2-.5-1.2-1.2z" />
  ),
  // doc.on.doc
  copy: (
    <>
      <rect x="5.5" y="5.5" width="7.5" height="8" rx="1.6" />
      <path d="M10.5 5.5V3.6c0-.6-.5-1.1-1.1-1.1H4.1c-.6 0-1.1.5-1.1 1.1v6.3c0 .6.5 1.1 1.1 1.1h1.4" />
    </>
  ),
  // gearshape
  gear: (
    <>
      <circle cx="8" cy="8" r="2.1" />
      <path d="M8 1.8v1.8M8 12.4v1.8M1.8 8h1.8M12.4 8h1.8M3.6 3.6l1.3 1.3M11.1 11.1l1.3 1.3M3.6 12.4l1.3-1.3M11.1 4.9l1.3-1.3" />
      <circle cx="8" cy="8" r="4.4" />
    </>
  ),
  // pin
  pin: <path d="M6 2.5h4M6.6 2.5v4L4.5 9h7L9.4 6.5v-4M8 9v4.5" />,
  // archivebox
  archive: (
    <>
      <rect x="2" y="3" width="12" height="3" rx="0.8" />
      <path d="M3 6v6.2c0 .7.5 1.2 1.2 1.2h7.6c.7 0 1.2-.5 1.2-1.2V6M6.5 8.6h3" />
    </>
  ),
  // pencil
  edit: <path d="M10.6 2.9 13 5.3l-7.6 7.6-3 .6.6-3zM9.4 4.1l2.4 2.4" />,
  // trash
  trash: (
    <path d="M2.8 4.3h10.4M6.3 4.3V2.8h3.4v1.5M4.2 4.3l.6 8.5c0 .5.4.8.9.8h4.6c.5 0 .9-.3.9-.8l.6-8.5M6.7 6.8v4.4M9.3 6.8v4.4" />
  ),
  // arrow.up.forward.square
  open: (
    <path d="M9 2.5h4.5V7M13.3 2.7 7.5 8.5M11.5 9.5v3.2c0 .5-.4.8-.8.8H3.3c-.4 0-.8-.3-.8-.8V5.3c0-.4.4-.8.8-.8h3.2" />
  ),
  // sparkles
  spark: (
    <path d="M6.5 2.5 7.6 5.9 11 7 7.6 8.1 6.5 11.5 5.4 8.1 2 7l3.4-1.1zM12 9.5l.6 1.6 1.6.6-1.6.6-.6 1.6-.6-1.6-1.6-.6 1.6-.6z" />
  ),
  // sidebar.right
  panel: (
    <>
      <rect x="2" y="3" width="12" height="10" rx="1.8" />
      <path d="M10 3v10" />
    </>
  ),
  // person.2
  people: (
    <>
      <circle cx="6" cy="5.5" r="2.1" />
      <path d="M2 13c0-2.2 1.8-3.6 4-3.6s4 1.4 4 3.6" />
      <path d="M10.3 3.6a2 2 0 0 1 0 3.8M11.6 9.6c1.4.4 2.4 1.6 2.4 3.4" />
    </>
  ),
  // eye
  eye: (
    <>
      <path d="M1.8 8S4.2 3.8 8 3.8 14.2 8 14.2 8 11.8 12.2 8 12.2 1.8 8 1.8 8z" />
      <circle cx="8" cy="8" r="2" />
    </>
  ),
  // eye.slash
  eyeSlash: (
    <>
      <path d="M1.8 8S4.2 3.8 8 3.8 14.2 8 14.2 8 11.8 12.2 8 12.2 1.8 8 1.8 8z" />
      <circle cx="8" cy="8" r="2" />
      <path d="m2.8 2.8 10.4 10.4" />
    </>
  ),
  // at
  at: (
    <>
      <circle cx="8" cy="8" r="2.4" />
      <path d="M10.4 8v1c0 1 .7 1.7 1.6 1.7S13.6 10 13.6 8A5.6 5.6 0 1 0 11 12.8" />
    </>
  ),
  // star
  star: <path d="m8 2.4 1.7 3.5 3.8.5-2.8 2.6.7 3.8L8 11l-3.4 1.8.7-3.8-2.8-2.6 3.8-.5z" />,
  // pause
  pause: <path d="M5.5 3.5v9M10.5 3.5v9" />,
  // play
  play: <path d="M5 3.3v9.4l7.4-4.7z" />,
  // clock
  clock: (
    <>
      <circle cx="8" cy="8" r="5.6" />
      <path d="M8 5v3.2l2.2 1.4" />
    </>
  ),
  // arrow.uturn.backward
  rewind: <path d="M3 4v3.3h3.3M3.3 7.2A5 5 0 1 1 4.6 11" />,
  // arrow.branch
  fork: (
    <>
      <circle cx="4.5" cy="3.5" r="1.4" />
      <circle cx="11.5" cy="3.5" r="1.4" />
      <circle cx="8" cy="12.5" r="1.4" />
      <path d="M4.5 4.9v1.2c0 1.1.9 2 2 2h3c1.1 0 2-.9 2-2V4.9M8 8.1v3" />
    </>
  ),
  // rectangle.portrait.and.arrow.right
  sendAway: (
    <path d="M9.5 4.5V3.3c0-.5-.4-.8-.8-.8H3.3c-.5 0-.8.3-.8.8v9.4c0 .5.3.8.8.8h5.4c.4 0 .8-.3.8-.8v-1.2M6.5 8h7M11.3 5.8 13.5 8l-2.2 2.2" />
  ),
} satisfies Record<string, ReactNode>;

export type MenuIconName = keyof typeof PATHS;

/** A menu item's symbol, beside its title. */
export function MenuIcon({ name }: { name: MenuIconName }) {
  return (
    <svg className="dk-mico" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      {PATHS[name]}
    </svg>
  );
}
