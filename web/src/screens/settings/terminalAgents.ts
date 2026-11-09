// Settings > Terminal agents (B151) for both clients: the outside clients and their levels.
import { useCallback, useEffect, useState } from "react";
import type { OutsideAccess, OutsideClient, OutsideClientKind } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";

export const ACCESS_CHOICES: readonly { value: OutsideAccess; label: string }[] = [
  { value: "read", label: "Read only" },
  { value: "message", label: "Read and message" },
  { value: "full", label: "Full" },
];

// The level a client starts at when switched on.
export const FIRST_ACCESS: OutsideAccess = "read";

export function accessLabel(access: OutsideAccess | null): string {
  return ACCESS_CHOICES.find((c) => c.value === access)?.label ?? "Off";
}

/** The line to give an app that is not set up by Nest, or the command's own path. */
export function commandLine(client: OutsideClient): string | null {
  if (client.command === null || !(client.kind === "other" || client.kind === "shell")) {
    return null;
  }
  return client.command.map((part) => (/\s/.test(part) ? `"${part}"` : part)).join(" ");
}

/**
 * The clients, read again when the page comes back into view, and a change that shows the
 * client as the Mac reports it after. A refused change reads them again, as switching off
 * can be half done (off in Nest, still in the app's config).
 */
export function useTerminalAgents() {
  const { actions } = useStore();
  const [clients, setClients] = useState<OutsideClient[] | null>(null);
  const [busy, setBusy] = useState<OutsideClientKind | null>(null);
  const reload = useCallback(async () => {
    const found = await actions.outsideClients();
    if (found !== null) setClients(found);
  }, [actions]);
  useEffect(() => {
    const load = () => void reload();
    load();
    window.addEventListener("focus", load);
    return () => {
      window.removeEventListener("focus", load);
    };
  }, [reload]);
  const set = useCallback(
    async (kind: OutsideClientKind, access: OutsideAccess | null) => {
      setBusy(kind);
      const changed = await actions.setOutsideClient(kind, access);
      setBusy(null);
      if (changed === null) {
        await reload();
        return;
      }
      setClients((now) => now?.map((c) => (c.kind === kind ? changed : c)) ?? null);
    },
    [actions, reload],
  );
  return { clients, busy, set };
}
