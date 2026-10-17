import { Icon } from "../../ui/Icon.tsx";

interface Props {
  // None where a heading would repeat the page's title: the button stands alone.
  title?: string;
  // 2 on the details panel, 3 on its pages.
  level?: 2 | 3;
  // The button's accessible name, such as "Add skill".
  label: string;
  // What the button shows.
  text?: "Add" | "New";
  // The button opens a sheet.
  popup?: boolean;
  onAdd: () => void;
}

/** A heading with its Add or New button at the full right of the row (B85). */
export function AddHeading({ title, level = 2, label, text = "Add", popup, onAdd }: Props) {
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <div className="pxhrow">
      {title !== undefined && <Heading className={level === 2 ? "pg-h" : "pxsub"}>{title}</Heading>}
      <button
        className="pxhadd"
        aria-label={label}
        aria-haspopup={popup === true ? "dialog" : undefined}
        onClick={onAdd}
      >
        <Icon name="plus" />
        {text}
      </button>
    </div>
  );
}
