import { useState } from "react";
import type { Autonomy, PixieDefaults, ProjectAccess } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { CLAUDE, modelLabel } from "../../store/catalog.ts";
import { catalogFor, pixieList } from "../../store/selectors.ts";
import { AUTONOMY, PROJECT_ACCESS } from "../pixies/options.ts";
import type { PixieTab } from "../pixies/PixieView.tsx";
import { Sprite } from "../pixies/Sprite.tsx";
import { Loading, Section, SegRow, SelectRow, SwitchRow, type Choice } from "./rows.tsx";
import { withCurrent } from "./choices.ts";

const RUNNING = [1, 2, 3, 5];
const PER_DAY = [3, 5, 10, 20];
const HABIT_PERCENT = [70, 80, 90];

const pick = <T extends string>(choices: Record<T, { label: string }>): Choice<T>[] =>
  (Object.entries(choices) as [T, { label: string }][]).map(([value, { label }]) => ({
    value,
    label,
  }));

interface Props {
  onOpenPixie: (id: string, tab: PixieTab) => void;
}

/** Your pixies, then what new ones start with and the habits (B81). */
export function PixiesPage({ onOpenPixie }: Props) {
  const { state } = useStore();
  const settings = state.settings.pixies;
  return (
    <>
      <PixieList onOpenPixie={onOpenPixie} />
      {settings === null ? (
        <Loading title="New pixies start with" />
      ) : (
        <Defaults settings={settings} />
      )}
    </>
  );
}

function PixieList({ onOpenPixie }: Props) {
  const { state, actions } = useStore();
  const [showHidden, setShowHidden] = useState(false);
  const pixies = pixieList(state, showHidden);
  const hidden = pixieList(state, true).length - pixieList(state).length;
  const create = async () => {
    const created = await actions.createPixie({ name: "New pixie" });
    if (created !== null) onOpenPixie(created.id, "details");
  };
  return (
    <Section title="Your pixies">
      {pixies.map((p) => (
        <div key={p.id} className="srow">
          <span className="cn">
            <span className="sico" aria-hidden="true">
              <Sprite mascot={p.mascot} color={p.color} size={24} />
            </span>
            <span className="slab">
              {p.name}
              <span className="hint">{AUTONOMY[p.autonomy].label}</span>
            </span>
          </span>
          <button
            className="b"
            aria-label={`Open ${p.name}`}
            onClick={() => {
              onOpenPixie(p.id, "details");
            }}
          >
            Open
          </button>
        </div>
      ))}
      {hidden > 0 && (
        <SwitchRow
          label="Show hidden pixies"
          on={showHidden}
          onToggle={() => {
            setShowHidden(!showHidden);
          }}
        />
      )}
      <div className="srow">
        <button className="b" onClick={() => void create()}>
          New pixie
        </button>
      </div>
    </Section>
  );
}

function Defaults({ settings }: { settings: PixieDefaults }) {
  const { state, actions } = useStore();
  const save = (change: Partial<PixieDefaults>) =>
    void actions.saveSection("pixies", { ...settings, ...change }, settings);
  // Claude's real models: new pixies run on Claude, and none reads as its default (B94).
  const catalog = catalogFor(state, CLAUDE);
  const model = settings.model ?? catalog.defaultModel;
  const listed = catalog.models.some((m) => m.value === model);
  const modelChoices: Choice<string | null>[] = [
    ...catalog.models.map((m) => ({ value: m.value, label: m.display_name })),
    ...(listed ? [] : [{ value: model, label: modelLabel(catalog, model) }]),
  ];
  return (
    <>
      <Section title="New pixies start with">
        <SelectRow
          label="Model"
          value={model}
          choices={modelChoices}
          onChange={(model) => {
            save({ model });
          }}
        />
        <SelectRow<Autonomy>
          label="Autonomy"
          value={settings.autonomy}
          choices={pick(AUTONOMY)}
          onChange={(autonomy) => {
            save({ autonomy });
          }}
        />
        <SegRow<ProjectAccess>
          label="Project files"
          value={settings.project_access}
          choices={pick(PROJECT_ACCESS)}
          onChange={(project_access) => {
            save({ project_access });
          }}
        />
        <SelectRow
          label="Chats running at once"
          value={settings.max_running}
          choices={withCurrent(RUNNING, settings.max_running).map((n) => ({
            value: n,
            label: String(n),
          }))}
          onChange={(max_running) => {
            save({ max_running });
          }}
        />
        <SelectRow
          label="Chats started per day"
          value={settings.max_per_day}
          choices={withCurrent(PER_DAY, settings.max_per_day).map((n) => ({
            value: n,
            label: String(n),
          }))}
          onChange={(max_per_day) => {
            save({ max_per_day });
          }}
        />
      </Section>
      <Section title="Habits">
        <SwitchRow
          label="Pause all habits"
          on={settings.habits_paused}
          onToggle={() => {
            save({ habits_paused: !settings.habits_paused });
          }}
        />
        <SelectRow
          label="Skip habit runs above"
          value={settings.habit_usage_percent}
          choices={withCurrent(HABIT_PERCENT, settings.habit_usage_percent).map((n) => ({
            value: n,
            label: `${String(n)}%`,
          }))}
          onChange={(habit_usage_percent) => {
            save({ habit_usage_percent });
          }}
        />
      </Section>
    </>
  );
}
