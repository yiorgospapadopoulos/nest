import type { ReactNode } from "react";
import { EngineMark } from "../../shell/frame/marks.tsx";
import { Glyph, type GlyphName } from "../config/parts.tsx";
import "./accounts.css";

/**
 * An Accounts section's title line, as AccountsHeader.swift: a mark and the name in the
 * brightest text, so each engine, More engines, the local models and GitHub stand apart.
 */
export function AccountsHeader({ title, mark }: { title: string; mark: ReactNode }) {
  return (
    <h2 className="dka-head">
      {mark}
      {title}
    </h2>
  );
}

export function EngineHeader({ engine, title }: { engine: string; title: string }) {
  return <AccountsHeader title={title} mark={<EngineMark provider={engine} size={14} />} />;
}

/** A symbol in an engine mark's place. */
export function AccountsSymbol({ name }: { name: GlyphName }) {
  return <Glyph name={name} className="dka-symbol" />;
}

/** A thin bar of how much is used, as the Mac's Meter. */
export function Meter({ value, label }: { value: number; label: string }) {
  const percent = Math.max(0, Math.min(100, value));
  return (
    <span
      className="dka-meter"
      role="meter"
      aria-label={label}
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <i style={{ width: `${String(percent)}%` }} />
    </span>
  );
}

/** A row's "…" button, as RowActionsMenu's label. */
export function MoreGlyph() {
  return (
    <svg className="dka-more" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="3.5" cy="8" r="1.3" />
      <circle cx="8" cy="8" r="1.3" />
      <circle cx="12.5" cy="8" r="1.3" />
    </svg>
  );
}
