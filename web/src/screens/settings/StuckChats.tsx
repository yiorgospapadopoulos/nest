import type { StuckSettings } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Loading, Section, SelectRow } from "./rows.tsx";
import { withCurrent } from "./choices.ts";

// The thresholds and the values offered, as the Mac offers them; 0 turns a check off.
const THRESHOLDS: { key: keyof StuckSettings; label: string; values: number[] }[] = [
  { key: "waiting_minutes", label: "Waiting for you", values: [0, 5, 10, 15, 20, 30, 45, 60] },
  { key: "silent_minutes", label: "No output", values: [0, 5, 10, 15, 20, 30, 45, 60] },
  { key: "repeated_calls", label: "Same step repeated", values: [0, 3, 4, 5, 6, 8, 10] },
  { key: "turn_minutes", label: "One turn longer than", values: [0, 30, 45, 60, 90, 120, 180] },
];

/** "Off", "15 minutes", "1 hour 30 minutes", or "More than 4 times" for repeated calls. */
function thresholdLabel(key: keyof StuckSettings, value: number): string {
  if (value === 0) return "Off";
  if (key === "repeated_calls") return `More than ${String(value)} times`;
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  const hourText = hours === 1 ? "1 hour" : `${String(hours)} hours`;
  const minuteText = minutes === 1 ? "1 minute" : `${String(minutes)} minutes`;
  if (hours === 0) return minuteText;
  return minutes === 0 ? hourText : `${hourText} ${minuteText}`;
}

/** When a chat counts as stuck (D036); saved to the Mac at once. */
export function StuckChats() {
  const { state, actions } = useStore();
  const settings = state.settings.stuck;
  if (settings === null) return <Loading title="Stuck chats" />;
  return (
    <Section title="Stuck chats">
      {THRESHOLDS.map(({ key, label, values }) => (
        <SelectRow
          key={key}
          label={label}
          value={settings[key]}
          choices={withCurrent(values, settings[key]).map((v) => ({
            value: v,
            label: thresholdLabel(key, v),
          }))}
          onChange={(value) =>
            void actions.saveSection("stuck", { ...settings, [key]: value }, settings)
          }
        />
      ))}
    </Section>
  );
}
