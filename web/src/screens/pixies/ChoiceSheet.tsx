import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";

interface Props {
  title: string;
  choices: { key: string; label: string }[];
  // The key chosen now, ticked.
  current: string;
  onPick: (key: string) => void;
  onClose: () => void;
}

/** One choice from a short list, such as a pixie's team or a team's leader (B40). */
export function ChoiceSheet({ title, choices, current, onPick, onClose }: Props) {
  return (
    <ActionSheet label={title} title={<b>{title}</b>} onClose={onClose}>
      {choices.map((choice) => (
        <button
          key={choice.key}
          className="asi"
          role="menuitemradio"
          aria-checked={choice.key === current}
          data-autofocus={choice.key === current ? true : undefined}
          onClick={() => {
            onClose();
            onPick(choice.key);
          }}
        >
          <span>{choice.label}</span>
          <Icon name="check" className="ck2" />
        </button>
      ))}
    </ActionSheet>
  );
}
