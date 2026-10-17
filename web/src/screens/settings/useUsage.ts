import { useEffect } from "react";
import { useStore } from "../../store/context.ts";
import { isoDay } from "./usageText.ts";

/** The usage period shown in Settings, loaded whenever it changes (B84). */
export function useUsage(today: Date) {
  const { state, actions } = useStore();
  const { unit, date, period } = state.usage;
  const shown = date ?? isoDay(today);
  useEffect(() => {
    void actions.loadUsage(unit, shown);
  }, [actions, unit, shown]);
  return { unit, date: shown, period };
}
