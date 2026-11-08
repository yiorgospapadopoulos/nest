import type { WorktreeSettings } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { ownText } from "../project/worktree.ts";
import { TextRow } from "../project/parts.tsx";
import { SettingsSection, SwitchRow } from "../rows.tsx";

/** How Nest makes and tidies worktrees in every project (B141); a project can choose its own. */
export function WorktreesSection({ settings }: { settings: WorktreeSettings | null }) {
  const { actions } = useStore();
  const save = (change: Partial<WorktreeSettings>) => {
    if (settings !== null)
      void actions.saveSection("worktrees", { ...settings, ...change }, settings);
  };
  const disabled = settings === null;
  return (
    <SettingsSection title="Worktrees">
      <TextRow
        label="Worktrees folder"
        value={settings?.folder ?? null}
        unset="Inside each project"
        message="Each project gets a folder in it. Leave it empty to keep them inside each project."
        placeholder="~/worktrees"
        disabled={disabled}
        onSave={(text) => {
          save({ folder: ownText(text) });
        }}
      />
      <TextRow
        label="Branch name prefix"
        value={settings?.branch_prefix ?? null}
        unset="-"
        message="New worktree branches start with this."
        placeholder="agent/"
        disabled={disabled}
        onSave={(text) => {
          save({ branch_prefix: text.trim() });
        }}
      />
      <SwitchRow
        label="Check out submodules"
        on={settings?.submodules ?? false}
        disabled={disabled}
        onChange={(submodules) => {
          save({ submodules });
        }}
      />
      <SwitchRow
        label="Remove merged worktrees"
        on={settings?.clean_merged ?? false}
        disabled={disabled}
        onChange={(clean_merged) => {
          save({ clean_merged });
        }}
      />
    </SettingsSection>
  );
}
