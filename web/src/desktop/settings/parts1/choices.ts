import type { MenuEntry } from "../../ui/menuItems.ts";

/** A Dropdown's items for a list of values, the current one checked. */
export function choiceItems<T>(
  values: readonly T[],
  current: T,
  title: (value: T) => string,
  choose: (value: T) => void,
): MenuEntry[] {
  return values.map((value) => ({
    title: title(value),
    checked: Object.is(value, current),
    onSelect: () => {
      if (!Object.is(value, current)) choose(value);
    },
  }));
}
