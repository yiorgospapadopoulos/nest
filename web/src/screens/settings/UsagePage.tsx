import { UsageLimits } from "./UsageLimits.tsx";

/**
 * The limits, the periods Nest counted and the usage settings (B86, moved from Agents); Details
 * opens the breakdown (B84).
 */
export function UsagePage({ onDetails }: { onDetails: () => void }) {
  return <UsageLimits onDetails={onDetails} />;
}
