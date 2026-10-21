import { useState, type ReactNode } from "react";
import type { Tone } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";

interface Props {
  // Names the whole item, such as "Permission: Fix the header".
  label: string;
  tone: Tone;
  // The chat's (or pixie's) name, which opens it.
  name: string;
  onOpen: () => void;
  // The grey line under the name.
  line: ReactNode;
  openByDefault?: boolean;
  // The full item, shown in place while open; false for none, as a goal without steps.
  children: ReactNode;
}

/**
 * One row of Needs you or Goals, as the Mac's FoldRow (B77, B102 items 10, 11): the status
 * dot, the name over one grey line, and a chevron on the right. A tap anywhere else on the
 * row opens or closes the full item below it; the name keeps its own tap.
 */
export function FoldRow({
  label,
  tone,
  name,
  onOpen,
  line,
  openByDefault = false,
  children,
}: Props) {
  const [open, setOpen] = useState(openByDefault);
  const toggle = () => {
    setOpen(!open);
  };
  return (
    <article className="nitem" aria-label={label}>
      <div className="nrow" onClick={toggle}>
        <Dot tone={tone} />
        <span className="nbody">
          <button
            className="nname"
            onClick={(event) => {
              event.stopPropagation();
              onOpen();
            }}
          >
            {name}
          </button>
          <span className="nline">{line}</span>
        </span>
        <button
          className="nchev"
          aria-expanded={open}
          aria-label={open ? "Hide details" : "Show details"}
          onClick={(event) => {
            event.stopPropagation();
            toggle();
          }}
        >
          <Icon name="chev" />
        </button>
      </div>
      {open && children !== false && <div className="nexp">{children}</div>}
    </article>
  );
}
