import { useState } from "react";
import type { Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Icon, type IconName } from "../../ui/Icon.tsx";
import { ActionSheet, Sheet } from "../../ui/Sheet.tsx";

interface Props {
  session: Session;
  onClose: () => void;
  // Called after the chat was archived or deleted, so an open chat view can close.
  onGone?: () => void;
}

/** Pin, rename, archive and delete a chat, from the list or the chat header. */
export function ChatActions({ session, onClose, onGone }: Props) {
  const { actions } = useStore();
  const [step, setStep] = useState<"menu" | "rename" | "delete">("menu");
  const [title, setTitle] = useState(session.title);
  const archived = session.archived_at !== null;

  const finish = async (done: Promise<boolean>, gone = false) => {
    if (await done) {
      onClose();
      if (gone) onGone?.();
    }
  };

  if (step === "rename") {
    const save = () => {
      const value = title.trim();
      if (!value) {
        actions.toast("Type a title", "error");
        return;
      }
      void finish(actions.update(session.id, { title: value }, `Renamed to ${value}`));
    };
    return (
      <Sheet
        title="Rename"
        onClose={onClose}
        leading={
          <button className="done l" onClick={onClose}>
            Cancel
          </button>
        }
        trailing={
          <button className="done" onClick={save}>
            Save
          </button>
        }
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <label className="sr" htmlFor="rename-title">
            Chat title
          </label>
          <input
            id="rename-title"
            className="rin2"
            value={title}
            autoComplete="off"
            data-autofocus
            onChange={(e) => {
              setTitle(e.target.value);
            }}
          />
        </form>
      </Sheet>
    );
  }

  if (step === "delete") {
    return (
      <ActionSheet
        label="Delete this chat?"
        role="alertdialog"
        onClose={onClose}
        title={
          <>
            <b>Delete this chat?</b>
            {session.title} is removed with its worktree, branch and history.
          </>
        }
      >
        <button className="asi dng mid" onClick={() => void finish(actions.remove(session), true)}>
          Delete chat
        </button>
      </ActionSheet>
    );
  }

  const items: { id: string; label: string; icon: IconName; run: () => void }[] = [
    ...(archived
      ? []
      : [
          {
            id: "pin",
            label: session.pinned ? "Unpin" : "Pin",
            icon: "pin" as const,
            run: () =>
              void finish(
                actions.update(
                  session.id,
                  { pinned: !session.pinned },
                  `${session.pinned ? "Unpinned" : "Pinned"} ${session.title}`,
                ),
              ),
          },
        ]),
    {
      id: "rename",
      label: "Rename",
      icon: "edit",
      run: () => {
        setStep("rename");
      },
    },
    {
      id: "archive",
      label: archived ? "Unarchive" : "Archive",
      icon: "archive",
      run: () =>
        void finish(
          actions.update(
            session.id,
            { archived: !archived },
            `${archived ? "Unarchived" : "Archived"} ${session.title}`,
          ),
          !archived,
        ),
    },
  ];

  return (
    <ActionSheet
      label={`Actions for ${session.title}`}
      title={<b>{session.title}</b>}
      onClose={onClose}
    >
      {items.map((item) => (
        <button key={item.id} className="asi" role="menuitem" onClick={item.run}>
          <Icon name={item.icon} />
          <span>{item.label}</span>
        </button>
      ))}
      <button
        className="asi dng"
        role="menuitem"
        onClick={() => {
          setStep("delete");
        }}
      >
        <Icon name="trash" />
        <span>Delete</span>
      </button>
    </ActionSheet>
  );
}
