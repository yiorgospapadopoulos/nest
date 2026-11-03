import { useId, type CSSProperties, type ReactNode } from "react";
import { Icon, type IconName } from "../../ui/Icon.tsx";
import { Menu } from "../ui/Menu.tsx";
import type { MenuEntry } from "../ui/menuItems.ts";
import { RenameField } from "../ui/RenameField.tsx";
import { Toggle } from "../ui/controls.tsx";

// The Settings pages' building blocks, as SettingsWindow.swift's: a small grey section
// title over rows separated by thin lines, each row a label on the left and its control
// on the right.

interface SectionProps {
  title?: string;
  // Rows draw their own lines; other content, such as a list, goes in bare.
  bare?: boolean;
  // A quiet note at the title's far end, with its icon, such as "Drag to reorder".
  hint?: { icon?: IconName; text: string };
  // Controls at the title's far end, such as Add.
  tools?: ReactNode;
  children: ReactNode;
}

export function SettingsSection({ title, bare = false, hint, tools, children }: SectionProps) {
  const id = useId();
  const titled = title !== undefined && title !== "";
  return (
    <section className="dks-sec" aria-labelledby={titled ? id : undefined}>
      {titled && (
        <div className="dks-sech">
          <h2 id={id}>{title}</h2>
          {hint !== undefined && (
            <span className="dks-hint">
              {hint.icon !== undefined && <Icon name={hint.icon} />}
              {hint.text}
            </span>
          )}
          {tools !== undefined && <span className="dks-tools">{tools}</span>}
        </div>
      )}
      {bare ? children : <div className="dks-rows">{children}</div>}
    </section>
  );
}

interface RowProps {
  label: ReactNode;
  // Before the label, such as a grip or an icon.
  leading?: ReactNode;
  // Names the control by the label.
  labelId?: string;
  children?: ReactNode;
}

/** A label on the left and its control on the right, over a thin line. */
export function SettingsRow({ label, leading, labelId, children }: RowProps) {
  return (
    <div className="dks-row">
      <span className="dks-lab">
        {leading}
        <span id={labelId}>{label}</span>
      </span>
      {children !== undefined && <span className="dks-ctl">{children}</span>}
    </div>
  );
}

/** A row with a switch named by its label. */
export function SwitchRow({
  label,
  on,
  onChange,
  disabled = false,
}: {
  label: string;
  on: boolean;
  onChange: (on: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <SettingsRow label={label}>
      <Toggle checked={on} onChange={onChange} label={label} disabled={disabled} />
    </SettingsRow>
  );
}

interface ListRowProps {
  title: string;
  detail?: string | null;
  mono?: boolean;
  // A line under the detail in the wait colour, with the warning sign.
  warning?: string | null;
  // While set, the title is a field that edits it in place.
  rename?: { initial: string; done: (name: string | null) => void } | null;
  leading?: ReactNode;
  trailing?: ReactNode;
}

/** A list row: an icon, a title with an optional line under it, and its controls. */
export function SettingsListRow({
  title,
  detail,
  mono = false,
  warning,
  rename,
  leading,
  trailing,
}: ListRowProps) {
  return (
    <div className="dks-lrow">
      {leading}
      <span className="dks-ltext">
        {rename != null ? (
          <RenameField
            value={rename.initial}
            label="Name"
            className="dks-lrename"
            onCommit={(name) => {
              rename.done(name);
            }}
            onCancel={() => {
              rename.done(null);
            }}
          />
        ) : (
          <span className="dks-ltitle">{title}</span>
        )}
        {detail != null && detail !== "" && (
          <span className={mono ? "dks-ldetail mono" : "dks-ldetail"}>{detail}</span>
        )}
        {warning != null && warning !== "" && <WarningLine text={warning} />}
      </span>
      {trailing !== undefined && <span className="dks-ctl">{trailing}</span>}
    </div>
  );
}

/** A line in the wait colour with the warning sign. */
export function WarningLine({ text }: { text: string }) {
  return (
    <span className="dks-warn">
      <svg viewBox="0 0 12 12" aria-hidden="true">
        <path d="M6 1.5 11 10.5H1z" />
        <path d="M6 5v2.4M6 8.9v.1" />
      </svg>
      {text}
    </span>
  );
}

/** A boxed checkmark, filled while on: one of several choices. */
export function CheckBox({ on }: { on: boolean }) {
  return (
    <span className={on ? "dks-check on" : "dks-check"} aria-hidden="true">
      <svg viewBox="0 0 12 12">
        <path d="M2.8 6.2 5 8.4l4.2-4.8" />
      </svg>
    </span>
  );
}

/** A list's square badge: a letter or two, or an icon. */
export function Badge({ text, icon }: { text?: string; icon?: IconName }) {
  return (
    <span className="dks-badge" aria-hidden="true">
      {icon !== undefined ? <Icon name={icon} /> : text}
    </span>
  );
}

/** Text in the secondary colour beside a control, in mono for paths and addresses. */
export function Value({ text, mono = false }: { text: string; mono?: boolean }) {
  return <span className={mono ? "dks-val mono" : "dks-val"}>{text}</span>;
}

/** Small underlined tabs, such as a project page's. */
export function SettingsTabs<T extends string>({
  tabs,
  selection,
  onSelect,
  label,
}: {
  tabs: readonly (readonly [T, string])[];
  selection: T;
  onSelect: (tab: T) => void;
  label: string;
}) {
  return (
    <div className="dks-tabs" role="tablist" aria-label={label}>
      {tabs.map(([tab, title]) => (
        <button
          key={tab}
          role="tab"
          aria-selected={tab === selection}
          className={tab === selection ? "on" : undefined}
          onClick={() => {
            onSelect(tab);
          }}
        >
          {title}
        </button>
      ))}
    </div>
  );
}

/** A short failure line under a control. */
export function Failure({ text }: { text: string }) {
  return <p className="dks-fail">{text}</p>;
}

/** A quiet line of text inside a section, such as "Loading" or an empty list. */
export function Note({ children }: { children: ReactNode }) {
  return <p className="dks-note">{children}</p>;
}

/**
 * The Mac's DropdownMenu (GeneralPages.swift): a small soft button of a fixed width with
 * the value and a chevron, opening an anchored menu of the choices.
 */
export function Dropdown({
  label,
  title,
  items,
  width = 160,
  disabled = false,
}: {
  // Names the menu and the button for assistive technology.
  label: string;
  title: string;
  items: MenuEntry[] | (() => MenuEntry[]);
  width?: number;
  disabled?: boolean;
}) {
  return (
    <Menu label={label} items={items} align="end">
      {(trigger) => (
        <button
          {...trigger}
          type="button"
          className="dks-drop"
          style={{ "--w": `${String(width)}px` } as CSSProperties}
          aria-label={`${label}: ${title}`}
          disabled={disabled}
        >
          <span>{title}</span>
          <svg viewBox="0 0 10 10" aria-hidden="true">
            <path d="M2.2 3.8 5 6.6l2.8-2.8" />
          </svg>
        </button>
      )}
    </Menu>
  );
}
