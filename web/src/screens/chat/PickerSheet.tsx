import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";
import type { Option } from "./options.ts";

interface Props {
  title: string;
  options: Option<string>[];
  value: string | null;
  onPick: (value: string) => void;
  onClose: () => void;
}

export function PickerSheet({ title, options, value, onPick, onClose }: Props) {
  return (
    <ActionSheet label={title} title={<b>{title}</b>} onClose={onClose}>
      {options.map((option) => (
        <button
          key={option.value}
          className="asi"
          role="menuitemradio"
          aria-checked={option.value === value}
          data-autofocus={option.value === value ? true : undefined}
          onClick={() => {
            onPick(option.value);
            onClose();
          }}
        >
          <span>
            <span>{option.label}</span>
            {option.hint !== undefined && <small>{option.hint}</small>}
          </span>
          <Icon name="check" className="ck2" />
        </button>
      ))}
    </ActionSheet>
  );
}
