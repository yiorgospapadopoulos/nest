import { SheetFrame } from "../sheets/SheetFrame.tsx";
import { Button } from "../ui/controls.tsx";

interface Props {
  title: string;
  message: string;
  action: string;
  // A destructive action shows in red.
  destructive?: boolean;
  onConfirm: () => void;
  // Cancel, Escape, Ctrl+W or a press outside; also after the action.
  onClose: () => void;
}

/** The Mac's confirmation dialog: the question, what it does, the action and Cancel. */
export function ConfirmDialog({
  title,
  message,
  action,
  destructive = false,
  onConfirm,
  onClose,
}: Props) {
  return (
    <SheetFrame
      title={title}
      width={420}
      onClose={onClose}
      footer={
        <>
          <Button size="large" data-autofocus onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="large"
            kind={destructive ? "destructive" : "primary"}
            onClick={() => {
              onConfirm();
              onClose();
            }}
          >
            {action}
          </Button>
        </>
      }
    >
      <p className="da-confirm">{message}</p>
    </SheetFrame>
  );
}
