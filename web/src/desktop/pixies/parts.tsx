// The rows and headings of the details panel and its pages (PixieDetails.swift's
// DetailHeading, DrillInRow, PickerRow, DangerRow, DetailNote and PixieFilePage.swift's
// PanelPageHeader), in the panel's 8 point inset.
import type { ReactNode } from "react";
import { Button } from "../ui/controls.tsx";
import { Menu } from "../ui/Menu.tsx";
import type { MenuEntry } from "../ui/menuItems.ts";
import { PxGlyph } from "./glyphs.tsx";
import "./details.css";

/** A line across the whole panel between parts of the details. */
export function SectionBreak() {
  return <hr className="pd-break" />;
}

/** A small grey label, after a line across the panel unless it opens the page, its Add at the right. */
export function DetailHeading({
  title,
  divided = true,
  children,
}: {
  title: string;
  divided?: boolean;
  children?: ReactNode;
}) {
  return (
    <>
      {divided && <SectionBreak />}
      <h3 className={divided ? "pd-heading" : "pd-heading first"}>
        <span>{title}</span>
        {children}
      </h3>
    </>
  );
}

export function DetailNote({ text }: { text: string }) {
  return <p className="pd-note">{text}</p>;
}

export function DetailLine({ text, dim }: { text: string; dim: boolean }) {
  return <p className={dim ? "pd-line dim" : "pd-line"}>{text}</p>;
}

/** A row that opens a page: title, a line about it, a count or note, and a chevron. */
export function DrillInRow({
  title,
  about,
  value,
  onOpen,
}: {
  title: string;
  about: string;
  value?: string | null;
  onOpen: () => void;
}) {
  return (
    <button
      className="pd-drill"
      aria-label={value == null ? title : `${title}, ${value}`}
      onClick={onOpen}
    >
      <span className="pd-drill-t">
        <span>{title}</span>
        <small>{about}</small>
      </span>
      {value != null && <span className="pd-drill-v">{value}</span>}
      <PxGlyph name="chevronRight" className="pd-chev" />
    </button>
  );
}

/** A red action at the bottom, such as Reset conversation. */
export function DangerRow({
  title,
  about,
  onClick,
}: {
  title: string;
  about?: string;
  onClick: () => void;
}) {
  return (
    <button className="pd-danger" onClick={onClick}>
      <span>{title}</span>
      {about !== undefined && <small>{about}</small>}
    </button>
  );
}

/** A title on the left and the value on the right; a click opens the choices below it. */
export function PickerRow({
  title,
  value,
  items,
  enabled = true,
}: {
  title: string;
  value: string;
  items: () => MenuEntry[];
  enabled?: boolean;
}) {
  return (
    <Menu label={title} items={items} align="end">
      {(trigger) => (
        <button
          {...trigger}
          className="pd-picker"
          aria-label={`${title}: ${value}`}
          disabled={!enabled}
        >
          <span className="pd-picker-t">{title}</span>
          <span className="pd-picker-v">{value}</span>
          <PxGlyph name="upDown" className="pd-updown" />
        </button>
      )}
    </Menu>
  );
}

/** A value with a stepper, saved at once within its range. */
export function StepperRow({
  title,
  value,
  shown,
  min,
  max,
  onChange,
}: {
  title: string;
  value: number;
  shown?: string;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  const text = shown ?? String(value);
  const set = (next: number) => {
    const clamped = Math.min(max, Math.max(min, next));
    if (clamped !== value) onChange(clamped);
  };
  return (
    <div
      className="pd-stepper"
      role="spinbutton"
      aria-label={title}
      aria-valuenow={value}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuetext={`${title}: ${text}`}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "ArrowUp") set(value + 1);
        else if (event.key === "ArrowDown") set(value - 1);
        else return;
        event.preventDefault();
      }}
    >
      <span className="pd-stepper-t">{title}</span>
      <span className="pd-stepper-v">{text}</span>
      <span className="pd-steps" aria-hidden="true">
        <button
          tabIndex={-1}
          disabled={value >= max}
          onClick={() => {
            set(value + 1);
          }}
        >
          <svg viewBox="0 0 10 6">
            <path d="M2 4.5 5 1.5l3 3" />
          </svg>
        </button>
        <button
          tabIndex={-1}
          disabled={value <= min}
          onClick={() => {
            set(value - 1);
          }}
        >
          <svg viewBox="0 0 10 6">
            <path d="M2 1.5 5 4.5l3-3" />
          </svg>
        </button>
      </span>
    </div>
  );
}

/** A small x that removes the thing beside it. */
export function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button className="pd-remove" title={label} aria-label={label} onClick={onClick}>
      <PxGlyph name="close" />
    </button>
  );
}

/** "+ Add" at the right of a heading, the one place every Add of the details sits (B85). */
export function HeadingAddButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button kind="plain" className="pd-add" title={label} aria-label={label} onClick={onClick}>
      <PxGlyph name="plus" />
      Add
    </Button>
  );
}

/** The same Add, opening a menu of what to add. */
export function HeadingAddMenu({ label, items }: { label: string; items: () => MenuEntry[] }) {
  return (
    <Menu label={label} items={items} align="end">
      {(trigger) => (
        <button {...trigger} className="dk-btn k-plain pd-add" title={label} aria-label={label}>
          <PxGlyph name="plus" />
          Add
        </button>
      )}
    </Menu>
  );
}

/** A page's back button, its title in the middle and an action on the right. */
export function PanelPageHeader({
  title,
  back,
  onBack,
  children,
}: {
  title: string;
  back: string;
  onBack: () => void;
  children?: ReactNode;
}) {
  return (
    <header className="pd-pagehead">
      <Button kind="plain" title={`Back to ${back}`} onClick={onBack}>
        <PxGlyph name="chevronLeft" />
        {back}
      </Button>
      <h2>{title}</h2>
      <span className="pd-pagehead-r">{children}</span>
    </header>
  );
}

/** A page under its header: the header stays, the rest scrolls. */
export function Page({ header, children }: { header: ReactNode; children: ReactNode }) {
  return (
    <div className="pd-page">
      {header}
      <div className="pd-scroll">{children}</div>
    </div>
  );
}
