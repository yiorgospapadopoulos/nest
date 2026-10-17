/** A value list with the current value added when it is not among them, in order. */
export function withCurrent<T extends number>(values: readonly T[], current: T): readonly T[] {
  return values.includes(current) ? values : [...values, current].sort((a, b) => a - b);
}
