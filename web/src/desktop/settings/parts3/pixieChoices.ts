// The numbers Settings > Pixies offers, as NestKit's PixieSettingsText.

export const MAX_RUNNING_CHOICES = [1, 2, 3, 5];
export const MAX_PER_DAY_CHOICES = [3, 5, 10, 20];
export const HABIT_USAGE_CHOICES = [70, 80, 90, 100];

/** The choices, with a value the daemon holds that is not one of them, in order. */
export function choicesWith(base: readonly number[], value: number | null): number[] {
  if (value === null || base.includes(value)) return [...base];
  return [...base, value].sort((a, b) => a - b);
}
