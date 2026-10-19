import { ActionSheet } from "../../ui/Sheet.tsx";

interface Props {
  title: string;
  about: string;
  action: string;
  onConfirm: () => void;
  onClose: () => void;
  // The action is not destructive, so it is not shown in the danger color.
  neutral?: boolean;
}

/** A question before something that cannot be undone; it opens on Cancel. */
export function Confirm({ title, about, action, onConfirm, onClose, neutral = false }: Props) {
  return (
    <ActionSheet
      label={title}
      role="alertdialog"
      onClose={onClose}
      title={
        <>
          <b>{title}</b>
          {about}
        </>
      }
    >
      <button
        className={neutral ? "asi mid" : "asi dng mid"}
        onClick={() => {
          onClose();
          onConfirm();
        }}
      >
        {action}
      </button>
    </ActionSheet>
  );
}
