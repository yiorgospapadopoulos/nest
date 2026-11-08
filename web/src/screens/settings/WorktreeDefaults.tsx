import type { WorktreeSettings } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Loading, Section, SwitchRow } from "./rows.tsx";
import { TextRow } from "./TextRow.tsx";

/** How Nest makes and tidies worktrees in every project (B141); saved to the Mac at once. */
export function WorktreeDefaults() {
  const { state, actions } = useStore();
  const settings = state.settings.worktrees;
  if (settings === null) return <Loading title="Worktrees" />;
  const save = (change: Partial<WorktreeSettings>) => {
    void actions.saveSection("worktrees", { ...settings, ...change }, settings);
  };
  return (
    <Section title="Worktrees">
      <TextRow
        label="Worktrees folder"
        value={settings.folder}
        unset="Inside each project"
        onSave={(text) => {
          save({ folder: text === "" ? null : text });
        }}
      />
      <TextRow
        label="Branch name prefix"
        value={settings.branch_prefix}
        unset="None"
        onSave={(branch_prefix) => {
          save({ branch_prefix });
        }}
      />
      <SwitchRow
        label="Check out submodules"
        on={settings.submodules}
        onToggle={() => {
          save({ submodules: !settings.submodules });
        }}
      />
      <SwitchRow
        label="Remove merged worktrees"
        on={settings.clean_merged}
        onToggle={() => {
          save({ clean_merged: !settings.clean_merged });
        }}
      />
    </Section>
  );
}
