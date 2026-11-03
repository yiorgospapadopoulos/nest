// The Artifacts view's symbols, drawn after the SF Symbols the Mac's view uses, on a 16
// unit grid with a thin stroke.
import type { ArtifactKind } from "../../api/types.ts";

const PATHS = {
  // doc.richtext
  richtext: (
    <>
      <path d="M4 1.8h5.2L12.5 5v8.6c0 .4-.3.6-.6.6H4c-.4 0-.6-.3-.6-.6V2.4c0-.4.3-.6.6-.6z" />
      <path d="M9 1.9V5.2h3.4M5.6 7.4h3.2M5.6 9.3h2.2" />
      <path d="M5.5 12.6 7 11l1.2 1 1.4-1.6 1.1 2.2" />
    </>
  ),
  // chevron.left.forwardslash.chevron.right
  code: <path d="M5 4.5 1.8 8 5 11.5M11 4.5 14.2 8 11 11.5M9.4 3.4 6.6 12.6" />,
  // play.rectangle
  slides: (
    <>
      <rect x="1.6" y="3" width="12.8" height="10" rx="1.8" />
      <path d="M6.6 6v4l3.4-2z" />
    </>
  ),
  // doc.text
  doctext: (
    <>
      <path d="M4 1.8h5.2L12.5 5v8.6c0 .4-.3.6-.6.6H4c-.4 0-.6-.3-.6-.6V2.4c0-.4.3-.6.6-.6z" />
      <path d="M9 1.9V5.2h3.4M5.6 7.6h4.8M5.6 9.6h4.8M5.6 11.6h3" />
    </>
  ),
  // rectangle.3.group
  design: (
    <>
      <rect x="1.8" y="2.2" width="5.4" height="5.2" rx="1" />
      <rect x="8.8" y="2.2" width="5.4" height="5.2" rx="1" />
      <rect x="1.8" y="8.8" width="12.4" height="5" rx="1" />
    </>
  ),
  // swatchpalette
  palette: (
    <>
      <rect x="1.8" y="1.8" width="4.6" height="12.4" rx="1.4" />
      <path d="M6.4 6.2 9.6 3a1 1 0 0 1 1.4 0l1.9 1.9a1 1 0 0 1 0 1.4L6.4 12.8" />
      <path d="M6.4 14.2h7a.8.8 0 0 0 .8-.8V10a.8.8 0 0 0-.8-.8H11" />
      <circle cx="4.1" cy="11.6" r=".7" fill="currentColor" stroke="none" />
    </>
  ),
  chevronLeft: <path d="M9.8 3.6 5.4 8l4.4 4.4" />,
  chevronRight: <path d="M6.2 3.6 10.6 8l-4.4 4.4" />,
  copy: (
    <>
      <rect x="5.5" y="5.5" width="7.5" height="8" rx="1.6" />
      <path d="M10.5 5.5V3.6c0-.6-.5-1.1-1.1-1.1H4.1c-.6 0-1.1.5-1.1 1.1v6.3c0 .6.5 1.1 1.1 1.1h1.4" />
    </>
  ),
  // square.and.arrow.down
  save: (
    <>
      <path d="M5.4 6.2H4.2c-.6 0-1 .4-1 1v5.6c0 .6.4 1 1 1h7.6c.6 0 1-.4 1-1V7.2c0-.6-.4-1-1-1h-1.2" />
      <path d="M8 1.8v8M5.4 7.4 8 10l2.6-2.6" />
    </>
  ),
  trash: (
    <>
      <path d="M2.6 4.2h10.8M6.2 4.2V2.8c0-.4.3-.6.6-.6h2.4c.4 0 .6.3.6.6v1.4" />
      <path d="M3.9 4.2l.6 9c0 .5.5.9 1 .9h5c.5 0 1-.4 1-.9l.6-9M6.6 6.6v5M9.4 6.6v5" />
    </>
  ),
  eraser: (
    <>
      <path d="M9.2 2.6a1.3 1.3 0 0 1 1.8 0l2.4 2.4a1.3 1.3 0 0 1 0 1.8L7.6 12.6H4.8L2.6 10.4a1.3 1.3 0 0 1 0-1.8z" />
      <path d="M5.6 6.2l4.2 4.2M7.6 12.6h6" />
    </>
  ),
} as const;

export type ArtifactGlyphName = keyof typeof PATHS;

const KIND_GLYPHS: Record<ArtifactKind, ArtifactGlyphName> = {
  markdown: "richtext",
  html: "code",
  slides: "slides",
  document: "doctext",
  design: "design",
  design_system: "palette",
};

export function Glyph({ name, className }: { name: ArtifactGlyphName; className?: string }) {
  return (
    <svg
      className={className === undefined ? "da-g" : `da-g ${className}`}
      viewBox="0 0 16 16"
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  );
}

/** The kind's symbol, as ArtifactKind.symbol. */
export function KindGlyph({ kind, className }: { kind: ArtifactKind; className?: string }) {
  return <Glyph name={KIND_GLYPHS[kind]} {...(className === undefined ? {} : { className })} />;
}
