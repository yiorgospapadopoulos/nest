import type { Session } from "../../api/types.ts";
import { Dot } from "../../ui/bits.tsx";
import { prView } from "./prView.ts";

/** The chat's pull request with a dot for its checks; opens it on GitHub. */
export function PrChip({ session }: { session: Session }) {
  if (session.pr_url === null) return null;
  const { label, tone, text } = prView(session.pr, session.pr_url);
  return (
    <a
      className="chip prchip"
      href={session.pr?.url ?? session.pr_url}
      target="_blank"
      rel="noreferrer"
      aria-label={`Pull request ${label}, ${text}`}
    >
      <Dot tone={tone} />
      <span>{label}</span>
    </a>
  );
}
