import { useId, type ReactNode } from "react";
import { Icon } from "../../ui/Icon.tsx";

// The Settings pages' building blocks (B81): a small grey section title over a rounded
// group of rows, each row a label on the left and its control on the right, nothing more.

/** A section: its title (if any), extra controls beside it, then its rows in a group. */
export function Section({
  title,
  tools,
  className,
  children,
}: {
  title?: string;
  tools?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section className={className} aria-labelledby={title === undefined ? undefined : id}>
      {title !== undefined && (
        <h2 className="pg-h" id={id}>
          {title}
          {tools}
        </h2>
      )}
      <div className="lgrp gl">{children}</div>
    </section>
  );
}

/** Rows not loaded yet. */
export function Loading({ title }: { title?: string }) {
  return (
    <Section {...(title === undefined ? {} : { title })}>
      <div className="srow note">Loading...</div>
    </Section>
  );
}

/** A label and its control; `labelId` names the control by the label. */
export function Row({
  label,
  children,
  labelId,
}: {
  label: ReactNode;
  children?: ReactNode;
  labelId?: string;
}) {
  return (
    <div className="srow">
      <span id={labelId} className="slab">
        {label}
      </span>
      {children !== undefined && <div className="sctl">{children}</div>}
    </div>
  );
}

export type StatusTone = "ok" | "wait" | "run" | "bad" | "idle";

/** A status as a quiet coloured word, as the Mac's settings show it: no pill. */
export function Status({ tone, label }: { tone: StatusTone; label: string }) {
  return <span className={`sst ${tone}`}>{label}</span>;
}

export function SwitchRow({
  label,
  on,
  onToggle,
  disabled = false,
}: {
  label: string;
  on: boolean;
  onToggle: () => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <Row label={label} labelId={id}>
      <button
        className="sw"
        role="switch"
        aria-checked={on}
        aria-labelledby={id}
        disabled={disabled}
        onClick={onToggle}
      />
    </Row>
  );
}

export interface Choice<T> {
  value: T;
  label: string;
}

/** A row with the system's list of choices; values are compared as text. */
export function SelectRow<T extends string | number | null>({
  label,
  value,
  choices,
  onChange,
  disabled = false,
}: {
  label: string;
  value: T;
  choices: readonly Choice<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const key = (v: T) => String(v);
  return (
    <div className="srow">
      <label htmlFor={id} className="slab">
        {label}
      </label>
      <select
        id={id}
        className="ssel"
        value={key(value)}
        disabled={disabled}
        onChange={(event) => {
          const picked = choices.find((c) => key(c.value) === event.target.value);
          if (picked !== undefined) onChange(picked.value);
        }}
      >
        {choices.map((c) => (
          <option key={key(c.value)} value={key(c.value)}>
            {c.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** A row with a segmented control; a long one goes under its label. */
export function SegRow<T>({
  label,
  value,
  choices,
  onChange,
  disabled = false,
  wide = false,
}: {
  label: string;
  value: T;
  choices: readonly Choice<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  wide?: boolean;
}) {
  const id = useId();
  return (
    <div className={wide ? "srow col" : "srow"}>
      <span id={id} className="slab">
        {label}
      </span>
      <div className="mseg" role="group" aria-labelledby={id}>
        {choices.map((c) => (
          <button
            key={c.label}
            aria-pressed={c.value === value}
            disabled={disabled}
            onClick={() => {
              onChange(c.value);
            }}
          >
            {c.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** A tappable row that opens another page, with a chevron and, if any, what is new there. */
export function LinkRow({
  icon,
  label,
  news,
  onOpen,
}: {
  icon: ReactNode;
  label: string;
  // Such as "3 new", shown with a dot.
  news?: string;
  onOpen: () => void;
}) {
  return (
    <button
      className="srow slink"
      aria-label={news === undefined ? undefined : `${label}, ${news}`}
      onClick={onOpen}
    >
      <span className="cn">
        {icon}
        <span>{label}</span>
      </span>
      {news !== undefined && (
        <span className="snew">
          {news}
          <span className="sdot" aria-hidden="true" />
        </span>
      )}
      <Icon name="chevr" className="schev" />
    </button>
  );
}

/** A page's bar: back on the left, the title in the middle, anything else on the right. */
export function PageFrame({
  title,
  back,
  onBack,
  extra,
  children,
}: {
  title: string;
  back: string;
  onBack: () => void;
  extra?: ReactNode;
  children: ReactNode;
}) {
  return (
    <>
      <div className="snav">
        <button className="back" aria-label={`Back to ${back}`} onClick={onBack} autoFocus>
          <Icon name="chevl" />
          <span>{back}</span>
        </button>
        <h1 className="snt">{title}</h1>
        {extra}
      </div>
      {children}
    </>
  );
}
