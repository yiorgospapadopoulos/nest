import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

// The Mac's NestButtonStyle kinds: filled in the accent, on a soft fill, text only, in the
// link colour, soft with red text, filled red.
export type ButtonKind = "primary" | "soft" | "plain" | "link" | "danger" | "destructive";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  kind?: ButtonKind;
  // 22 px, or 28 px with the larger text, as Metrics.buttonHeight and the sheets' buttons.
  size?: "regular" | "large";
  // A square button around an icon; give it an aria-label.
  iconOnly?: boolean;
}

/** A flat, small Mac button. */
export function Button({
  kind = "soft",
  size = "regular",
  iconOnly = false,
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  const classes = ["dk-btn", `k-${kind}`, size === "large" ? "large" : "", iconOnly ? "icon" : ""];
  if (className !== undefined) classes.push(className);
  return <button type={type} className={classes.filter(Boolean).join(" ")} {...rest} />;
}

interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange"> {
  label: string;
  onChange: (value: string) => void;
  mono?: boolean;
}

/** A soft-filled text field, as the Mac's inline fields; its label is for assistive technology. */
export function TextField({ label, onChange, mono = false, className, ...rest }: FieldProps) {
  const classes = ["dk-field", mono ? "mono" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <input
      className={classes}
      aria-label={label}
      spellCheck={false}
      autoComplete="off"
      {...rest}
      onChange={(event) => {
        onChange(event.target.value);
      }}
    />
  );
}

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}

/** A small switch, as the Mac's .switch toggles. */
export function Toggle({ checked, onChange, label, disabled = false }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      className="dk-switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => {
        onChange(!checked);
      }}
    >
      <span aria-hidden="true" />
    </button>
  );
}

interface SegmentedProps<T extends string> {
  label: string;
  value: T;
  options: { value: T; label: ReactNode; name?: string }[];
  onChange: (value: T) => void;
}

/** A segmented control, as the Mac's segmented pickers; arrows move the choice. */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: SegmentedProps<T>) {
  const move = (delta: number) => {
    const index = options.findIndex((o) => o.value === value);
    const next = options[(index + delta + options.length) % options.length];
    if (next !== undefined) onChange(next.value);
  };
  return (
    <div
      className="dk-segc"
      role="radiogroup"
      aria-label={label}
      onKeyDown={(event) => {
        if (event.key === "ArrowRight" || event.key === "ArrowDown") move(1);
        else if (event.key === "ArrowLeft" || event.key === "ArrowUp") move(-1);
        else return;
        event.preventDefault();
      }}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          aria-label={option.name}
          tabIndex={option.value === value ? 0 : -1}
          className={option.value === value ? "on" : undefined}
          onClick={() => {
            onChange(option.value);
          }}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

interface HoverRowProps {
  // The row itself, such as its button.
  children: ReactNode;
  // Shown at the row's trailing edge while the pointer is over it or the keyboard is in it.
  actions: ReactNode;
  // Keeps them shown, as while the row's "…" menu is open.
  revealed?: boolean;
  className?: string;
}

/** A row whose actions show on hover, as the Mac's hover controls on sidebar and list rows. */
export function HoverRow({ children, actions, revealed = false, className }: HoverRowProps) {
  return (
    <div className={className === undefined ? "dk-hrow" : `dk-hrow ${className}`}>
      {children}
      <span className="dk-hacts" data-revealed={revealed || undefined}>
        {actions}
      </span>
    </div>
  );
}
