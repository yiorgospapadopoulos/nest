import type { MouseEvent, ReactNode } from "react";
import "./config.css";

// The pieces Settings > Configuration, a project's Configuration tab and Accounts share,
// as ConfigurationView.swift's ConfigLabel, ConfigRow, ConfigSubRow, ConfigIcon, ConfigChip
// and the Theme's StatusLabel.

/** A small grey label over a part of the page. */
export function ConfigLabel({ text }: { text: string }) {
  return <h2 className="dkc-label">{text}</h2>;
}

/** A row of the page with a thin line over it. */
export function ConfigRow({ children }: { children: ReactNode }) {
  return <div className="dkc-row">{children}</div>;
}

/** A row under a row, indented: a skill, a server, a plugin. */
export function ConfigSubRow({
  children,
  onContextMenu,
}: {
  children: ReactNode;
  onContextMenu?: (event: MouseEvent<HTMLElement>) => void;
}) {
  return (
    <div className="dkc-sub" onContextMenu={onContextMenu}>
      {children}
    </div>
  );
}

/** The title and grey line of a row. */
export function RowText({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <span className="dkc-text">
      <span className="dkc-title">{title}</span>
      {children !== undefined && <span className="dkc-line">{children}</span>}
    </span>
  );
}

/** A small quiet chip, such as "yours" or "Codex". */
export function ConfigChip({ text, help }: { text: string; help?: string }) {
  return (
    <span className="dkc-chip" title={help}>
      {text}
    </span>
  );
}

export function EmptyLine({ text }: { text: string }) {
  return <p className="dkc-empty">{text}</p>;
}

/** The chevron of a fold, pointing down while open. */
export function FoldChevron({ open }: { open: boolean }) {
  return (
    <svg className={open ? "dkc-chev on" : "dkc-chev"} viewBox="0 0 10 10" aria-hidden="true">
      <path d="M2.2 3.8 5 6.6l2.8-2.8" />
    </svg>
  );
}

const GLYPHS = {
  doc: (
    <>
      <path d="M4 1.8h5l3 3v9.4H4z" />
      <path d="M9 1.8v3h3M6 8.5h4M6 11h4" />
    </>
  ),
  star: <path d="m8 1.8 1.9 3.9 4.2.6-3 3 .7 4.2L8 11.5l-3.8 2 .7-4.2-3-3 4.2-.6z" />,
  server: (
    <>
      <rect x="1.8" y="2.5" width="12.4" height="4.5" rx="1" />
      <rect x="1.8" y="9" width="12.4" height="4.5" rx="1" />
      <path d="M4.5 4.75h.1M4.5 11.25h.1" />
    </>
  ),
  laptop: (
    <>
      <rect x="3" y="3" width="10" height="7.5" rx="1" />
      <path d="M1.2 12.8h13.6" />
    </>
  ),
  chip: (
    <>
      <rect x="2" y="4.5" width="12" height="7" rx="1.5" />
      <path d="M5 2.8v1.7M8 2.8v1.7M11 2.8v1.7M5 11.5v1.7M8 11.5v1.7M11 11.5v1.7" />
    </>
  ),
  box: (
    <>
      <path d="m8 1.8 5.8 3v6.4L8 14.2l-5.8-3V4.8z" />
      <path d="m2.2 4.8 5.8 3 5.8-3M8 7.8v6.4" />
    </>
  ),
  pullRequest: (
    <>
      <circle cx="4" cy="3.5" r="1.6" />
      <circle cx="4" cy="12.5" r="1.6" />
      <circle cx="12" cy="12.5" r="1.6" />
      <path d="M4 5.1v5.8M12 10.9V6.5a2 2 0 0 0-2-2H7.5M9 3l-1.5 1.5L9 6" />
    </>
  ),
  agent: (
    <>
      <rect x="2.5" y="4.5" width="11" height="8.5" rx="2" />
      <path d="M8 2v2.5M6 8.5h.1M10 8.5h.1" />
    </>
  ),
} as const;

export type GlyphName = keyof typeof GLYPHS;

/** A line drawing in the SF Symbols' place, such as the server rack or the laptop. */
export function Glyph({ name, className }: { name: GlyphName; className?: string }) {
  return (
    <svg
      className={className === undefined ? "dkc-glyph" : `dkc-glyph ${className}`}
      viewBox="0 0 16 16"
      aria-hidden="true"
    >
      {GLYPHS[name]}
    </svg>
  );
}

/** A row's icon in the secondary colour. */
export function ConfigIcon({ name }: { name: GlyphName }) {
  return <Glyph name={name} className="dkc-icon" />;
}

export type StatusTone = "review" | "waiting" | "failed" | "running" | "done";

/** A status as the Mac's StatusLabel: a dot, filled or hollow, and the word in its tone. */
export function StatusLabel({
  tone,
  label,
  hollow = false,
}: {
  tone: StatusTone;
  label: string;
  hollow?: boolean;
}) {
  return (
    <span className={`dkc-status t-${tone}`}>
      <i className={hollow ? "hollow" : undefined} aria-hidden="true" />
      {label}
    </span>
  );
}

/** A label on the left of a form's field, as ConfigurationSheets.swift's FormLine. */
export function FormLine({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="dkc-form-line">
      <span>{label}</span>
      <div>{children}</div>
    </div>
  );
}

/** A few lines of plain text in mono, such as arguments. */
export function LinesField({
  placeholder,
  value,
  onChange,
}: {
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <textarea
      className="dkc-lines"
      aria-label={placeholder}
      placeholder={placeholder}
      spellCheck={false}
      autoComplete="off"
      value={value}
      onChange={(event) => {
        onChange(event.target.value);
      }}
    />
  );
}

/** A checkbox in the accent, with its label. */
export function Checkbox({
  on,
  label,
  onToggle,
}: {
  on: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={on}
      className={on ? "dkc-checkbox on" : "dkc-checkbox"}
      onClick={onToggle}
    >
      <i aria-hidden="true">
        <svg viewBox="0 0 12 12">
          <path d="M2.8 6.2 5 8.4l4.2-4.8" />
        </svg>
      </i>
      {label}
    </button>
  );
}

/** A few choices side by side, the chosen one in the accent, as the sheets' SegmentPicker. */
export function SegmentPicker<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly (readonly [T, string])[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="dkc-seg" role="radiogroup" aria-label={label}>
      {options.map(([option, title]) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={option === value}
          className={option === value ? "on" : undefined}
          onClick={() => {
            onChange(option);
          }}
        >
          {title}
        </button>
      ))}
    </div>
  );
}
