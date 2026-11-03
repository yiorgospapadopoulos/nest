import type { Autonomy, PixieDefaults, ProjectAccess } from "../../../api/types.ts";
import { AUTONOMY, PROJECT_ACCESS } from "../../../screens/pixies/options.ts";
import { CLAUDE, isSelected, modelLabel } from "../../../store/catalog.ts";
import { useStore } from "../../../store/context.ts";
import { catalogFor, pixieList } from "../../../store/selectors.ts";
import { Icon } from "../../../ui/Icon.tsx";
import { Sprite } from "../../pixies/Sprite.tsx";
import { useShell } from "../../shell/context.ts";
import { Button, Segmented } from "../../ui/controls.tsx";
import type { MenuEntry } from "../../ui/menuItems.ts";
import { Dropdown } from "../rows.tsx";
import {
  HABIT_USAGE_CHOICES,
  MAX_PER_DAY_CHOICES,
  MAX_RUNNING_CHOICES,
  choicesWith,
} from "../parts3/pixieChoices.ts";
import { Note, SettingsListRow, SettingsRow, SettingsSection, SwitchRow } from "../rows.tsx";
import "../parts3/parts3.css";

// What the page shows until the daemon's settings are read, as PixieSettings().
const UNLOADED: PixieDefaults = {
  model: null,
  autonomy: "observe",
  project_access: "edit",
  max_running: 2,
  max_per_day: 5,
  habits_paused: false,
  habit_usage_percent: 80,
};

const entries = <T extends string>(choices: Record<T, { label: string }>) =>
  Object.entries(choices) as [T, { label: string }][];

/**
 * The pixies with Open, Show hidden pixies and New pixie, then what new pixies start with
 * and the habits' switches, as the Mac's PixiesPage (B81).
 */
export function PixiesPage() {
  return (
    <>
      <PixieList />
      <PixieDefaultsSections />
    </>
  );
}

function PixieList() {
  const { state } = useStore();
  const shell = useShell();
  const pixies = pixieList(state, shell.showsHiddenPixies);
  return (
    <SettingsSection title="Your pixies" bare>
      <div className="dks3-list">
        {pixies.length === 0 && <Note>No pixies yet</Note>}
        {pixies.map((pixie) => (
          <SettingsListRow
            key={pixie.id}
            title={pixie.name}
            detail={pixie.hidden ? "Hidden" : AUTONOMY[pixie.autonomy].label}
            leading={
              <span
                className={pixie.hidden ? "dks3-sprite hidden" : "dks3-sprite"}
                aria-hidden="true"
              >
                <Sprite mascot={pixie.mascot} color={pixie.color} size={20} />
              </span>
            }
            trailing={
              <Button
                aria-label={`Open ${pixie.name}`}
                onClick={() => {
                  shell.closeSettings();
                  shell.openPixie(pixie.id);
                }}
              >
                Open
              </Button>
            }
          />
        ))}
      </div>
      <SwitchRow
        label="Show hidden pixies"
        on={shell.showsHiddenPixies}
        onChange={shell.setShowsHiddenPixies}
      />
      <div className="dks3-after">
        <Button
          onClick={() => {
            shell.closeSettings();
            shell.createPixie({ name: "New pixie" }, true);
          }}
        >
          <Icon name="plus" />
          New pixie
        </Button>
      </div>
    </SettingsSection>
  );
}

function PixieDefaultsSections() {
  const { state, actions } = useStore();
  const loaded = state.settings.pixies;
  const settings = loaded ?? UNLOADED;
  const disabled = loaded === null;
  const change = (next: Partial<PixieDefaults>) => {
    if (loaded !== null) void actions.saveSection("pixies", { ...loaded, ...next }, loaded);
  };
  // Claude's models: new pixies run on Claude, with no default entry (B94).
  const catalog = catalogFor(state, CLAUDE);
  const modelItems = (): MenuEntry[] => [
    { type: "section", title: "Model" },
    ...(catalog.models.length === 0
      ? [{ title: "Models unavailable", disabled: true, onSelect: () => undefined }]
      : catalog.models.map((info) => ({
          title: info.display_name,
          detail: info.description,
          checked: isSelected(catalog, info, settings.model),
          onSelect: () => {
            change({ model: info.value });
          },
        }))),
  ];
  const numbers = (
    label: string,
    value: number,
    base: readonly number[],
    pick: (value: number) => void,
    text: (value: number) => string = String,
    width = 70,
  ) => (
    <SettingsRow label={label}>
      <Dropdown
        label={label}
        title={text(value)}
        width={width}
        disabled={disabled}
        items={() =>
          choicesWith(base, value).map((choice) => ({
            title: text(choice),
            onSelect: () => {
              pick(choice);
            },
          }))
        }
      />
    </SettingsRow>
  );
  return (
    <>
      <SettingsSection title="New pixies start with">
        <SettingsRow label="Model">
          <Dropdown
            label="Model"
            title={modelLabel(catalog, settings.model)}
            disabled={disabled}
            items={modelItems}
          />
        </SettingsRow>
        <SettingsRow label="Autonomy">
          <Dropdown
            label="Autonomy"
            title={AUTONOMY[settings.autonomy].label}
            width={130}
            disabled={disabled}
            items={() =>
              entries<Autonomy>(AUTONOMY).map(([autonomy, { label }]) => ({
                title: label,
                onSelect: () => {
                  change({ autonomy });
                },
              }))
            }
          />
        </SettingsRow>
        <SettingsRow label="Project files">
          <fieldset className="dks3-plain" disabled={disabled}>
            <Segmented<ProjectAccess>
              label="Project files"
              value={settings.project_access}
              options={entries<ProjectAccess>(PROJECT_ACCESS).map(([value, { label }]) => ({
                value,
                label,
              }))}
              onChange={(project_access) => {
                change({ project_access });
              }}
            />
          </fieldset>
        </SettingsRow>
        {numbers("Chats running at once", settings.max_running, MAX_RUNNING_CHOICES, (n) => {
          change({ max_running: n });
        })}
        {numbers("Chats started per day", settings.max_per_day, MAX_PER_DAY_CHOICES, (n) => {
          change({ max_per_day: n });
        })}
      </SettingsSection>
      <SettingsSection title="Habits">
        <SwitchRow
          label="Pause all habits"
          on={settings.habits_paused}
          disabled={disabled}
          onChange={(habits_paused) => {
            change({ habits_paused });
          }}
        />
        {numbers(
          "Skip habit runs above",
          settings.habit_usage_percent,
          HABIT_USAGE_CHOICES,
          (n) => {
            change({ habit_usage_percent: n });
          },
          (n) => `${String(n)}%`,
          100,
        )}
      </SettingsSection>
    </>
  );
}
