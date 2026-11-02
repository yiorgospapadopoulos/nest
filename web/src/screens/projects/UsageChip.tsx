import { useEffect } from "react";
import { useStore } from "../../store/context.ts";
import { chipEntries, engineTitle } from "../../store/usageMeter.ts";

// The engines' short marks, as Settings > Accounts shows them.
const MARKS: Record<string, string> = { claude: "CL", codex: "CX" };

/**
 * The Chats header's usage (B116, option A): the top two accounts "Top bar shows" checks,
 * each as a thin bar and its shortest window ("63% 2h"), as the Mac's tab strip chip. The
 * second shows only when the header has room. Tapping opens Settings > Usage.
 */
export function UsageChip({ onOpen }: { onOpen: () => void }) {
  const { state, actions } = useStore();
  const accounts = state.settings.accounts;
  useEffect(() => {
    if (accounts === null) void actions.loadAccounts();
  }, [accounts, actions]);

  const entries = chipEntries(accounts ?? [], state.settings.usageMeter, new Date());
  if (entries.length === 0) return null;
  const label = entries.map((e) => `${engineTitle(e.provider)} ${e.text}`).join(", ");
  return (
    <button className="uchip" aria-label={`Usage: ${label}`} onClick={onOpen}>
      {entries.map((entry) => (
        <span key={entry.id} className={`uce ${entry.tone}`} aria-hidden="true">
          <span className="ucm">
            {MARKS[entry.provider] ?? entry.provider.slice(0, 2).toUpperCase()}
          </span>
          <span className="ucbar">
            <i style={{ width: `${String(Math.round(entry.used * 100))}%` }} />
          </span>
          {entry.text}
        </span>
      ))}
    </button>
  );
}
