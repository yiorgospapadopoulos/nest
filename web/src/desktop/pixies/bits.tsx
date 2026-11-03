// Small pieces the Pixies list, the details panel and the sheets share, as the Mac's
// CountBadge, StatusDot and RowActionsMenu.
import type { Tone } from "../../store/selectors.ts";
import { Menu } from "../ui/Menu.tsx";
import type { MenuEntry } from "../ui/menuItems.ts";
import { PxGlyph } from "./glyphs.tsx";

/** A count in the wait colour when it needs the user, else grey. */
export function CountBadge({ count, urgent }: { count: number; urgent: boolean }) {
  return <span className={urgent ? "px-count urgent" : "px-count"}>{count}</span>;
}

/** A small status dot in its tone's colour. */
export function StatusDot({ tone, hollow = false }: { tone: Tone; hollow?: boolean }) {
  return (
    <span className={hollow ? `px-dot s-${tone} hollow` : `px-dot s-${tone}`} aria-hidden="true" />
  );
}

/** The ⋯ of a row: a small soft square that opens the row's menu. */
export function RowActionsMenu({
  title,
  items,
  onOpenChange,
}: {
  title: string;
  items: () => MenuEntry[];
  onOpenChange?: (open: boolean) => void;
}) {
  return (
    <Menu
      label={`Actions for ${title}`}
      items={items}
      {...(onOpenChange === undefined ? {} : { onOpenChange })}
    >
      {(trigger) => (
        <button
          {...trigger}
          className="px-more"
          title="More"
          aria-label={`Actions for ${title}`}
          onDoubleClick={(event) => {
            event.stopPropagation();
          }}
        >
          <PxGlyph name="more" />
        </button>
      )}
    </Menu>
  );
}
