import { useState } from "react";
import type { Pixie, PixieTeam } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";
import { ChoiceSheet } from "./ChoiceSheet.tsx";
import { Confirm } from "./Confirm.tsx";
import { NameSheet } from "./NameSheet.tsx";

interface Props {
  team: PixieTeam;
  // Its members, hidden ones too, in list order.
  members: Pixie[];
  onClose: () => void;
}

/** A team header's menu: Rename, Change handle, Set leader and Delete team (B40). */
export function TeamActions({ team, members, onClose }: Props) {
  const { actions } = useStore();
  const [step, setStep] = useState<"menu" | "rename" | "handle" | "leader" | "delete">("menu");
  const [refused, setRefused] = useState<string | null>(null);

  const finish = async (done: Promise<boolean>) => {
    if (await done) onClose();
  };

  switch (step) {
    case "rename":
      return (
        <NameSheet
          title="Rename team"
          label="Team name"
          empty="Type a name"
          initial={team.name}
          action="Save"
          onSave={(name) => void finish(actions.updateTeam(team.id, { name }))}
          onClose={onClose}
        />
      );
    case "handle":
      return (
        <NameSheet
          title="Change handle"
          label="Handle"
          empty="Type a handle"
          initial={team.handle}
          action="Save"
          code
          refused={refused}
          onSave={(text) => {
            const handle = text.replace(/^@/, "");
            if (handle === team.handle) {
              onClose();
              return;
            }
            void actions.setTeamHandle(team.id, handle).then((why) => {
              setRefused(why);
              if (why === null) onClose();
            });
          }}
          onClose={onClose}
        />
      );
    case "leader":
      return (
        <ChoiceSheet
          title={`Leader of ${team.name}`}
          choices={members.map((p) => ({ key: p.id, label: p.name }))}
          current={String(team.leader_id)}
          onPick={(id) => void actions.updateTeam(team.id, { leader_id: id })}
          onClose={onClose}
        />
      );
    case "delete":
      return (
        <Confirm
          title={`Delete ${team.name}?`}
          about="Its pixies stay, without a team."
          action="Delete team"
          onConfirm={() => void actions.deleteTeam(team.id)}
          onClose={onClose}
        />
      );
    case "menu":
      return (
        <ActionSheet
          label={`Actions for team ${team.name}`}
          title={<b>{team.name}</b>}
          onClose={onClose}
        >
          <button
            className="asi"
            role="menuitem"
            onClick={() => {
              setStep("rename");
            }}
          >
            <Icon name="edit" />
            <span>Rename</span>
          </button>
          <button
            className="asi"
            role="menuitem"
            onClick={() => {
              setStep("handle");
            }}
          >
            <Icon name="edit" />
            <span>Change handle</span>
          </button>
          <button
            className="asi"
            role="menuitem"
            disabled={members.length === 0}
            onClick={() => {
              setStep("leader");
            }}
          >
            <Icon name="user" />
            <span>Set leader</span>
          </button>
          <button
            className="asi dng"
            role="menuitem"
            onClick={() => {
              setStep("delete");
            }}
          >
            <Icon name="trash" />
            <span>Delete team…</span>
          </button>
        </ActionSheet>
      );
  }
}
