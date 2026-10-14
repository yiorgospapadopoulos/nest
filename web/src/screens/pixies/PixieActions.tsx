import { useState } from "react";
import type { Pixie, PixieTeam } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Icon, type IconName } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";
import { ChoiceSheet } from "./ChoiceSheet.tsx";
import { Confirm } from "./Confirm.tsx";
import type { PixieTab } from "./PixieView.tsx";

// The choice that leaves the team.
const NO_TEAM = "";

interface Props {
  pixie: Pixie;
  teams: PixieTeam[];
  // Moves it past the pixie above or below it in its section; null at either end.
  onMoveUp: (() => void) | null;
  onMoveDown: (() => void) | null;
  onOpen: (id: string, tab: PixieTab) => void;
  onClose: () => void;
}

/**
 * A pixie row's menu (B40): Open, Details, Duplicate, Move to team, Move Up, Move Down,
 * Hide or Show, and Delete once confirmed.
 */
export function PixieActions({ pixie, teams, onMoveUp, onMoveDown, onOpen, onClose }: Props) {
  const { actions } = useStore();
  const [step, setStep] = useState<"menu" | "team" | "delete">("menu");

  if (step === "team") {
    return (
      <ChoiceSheet
        title={`Move ${pixie.name} to`}
        choices={[
          ...teams.map((t) => ({ key: t.id, label: t.name })),
          { key: NO_TEAM, label: "No team" },
        ]}
        current={pixie.team_id ?? NO_TEAM}
        onPick={(key) =>
          void actions.updatePixie(pixie.id, { team_id: key === NO_TEAM ? null : key })
        }
        onClose={onClose}
      />
    );
  }

  if (step === "delete") {
    return (
      <Confirm
        title={`Delete ${pixie.name}?`}
        about="Its chat, soul and memory go too. This can't be undone."
        action="Delete"
        onConfirm={() => void actions.deletePixie(pixie.id)}
        onClose={onClose}
      />
    );
  }

  // Closes the menu, then does `then`; null for a choice that is off.
  const run = (then: (() => void) | null) =>
    then &&
    (() => {
      onClose();
      then();
    });
  const items: { label: string; icon: IconName; run: (() => void) | null }[] = [
    {
      label: "Open",
      icon: "chevr",
      run: run(() => {
        onOpen(pixie.id, "chat");
      }),
    },
    {
      label: "Details",
      icon: "gear",
      run: run(() => {
        onOpen(pixie.id, "details");
      }),
    },
    {
      label: "Duplicate",
      icon: "plus",
      run: run(() => {
        void actions.duplicatePixie(pixie.id);
      }),
    },
    {
      label: "Move to team",
      icon: "folder",
      run: () => {
        setStep("team");
      },
    },
    { label: "Move Up", icon: "chev", run: run(onMoveUp) },
    { label: "Move Down", icon: "chev", run: run(onMoveDown) },
    {
      label: pixie.hidden ? "Show" : "Hide",
      icon: "archive",
      run: run(() => {
        void actions.updatePixie(pixie.id, { hidden: !pixie.hidden });
      }),
    },
  ];

  return (
    <ActionSheet label={`Actions for ${pixie.name}`} title={<b>{pixie.name}</b>} onClose={onClose}>
      {items.map((item) => (
        <button
          key={item.label}
          className="asi"
          role="menuitem"
          disabled={item.run === null}
          onClick={item.run ?? undefined}
        >
          <Icon name={item.icon} {...(item.label === "Move Up" ? { className: "up" } : {})} />
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
        <span>Delete…</span>
      </button>
    </ActionSheet>
  );
}
