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
 * client as the Mac reports it after; a refused change leaves it as it was.
 */
export function useTerminalAgents() {
  const { actions } = useStore();
  const [clients, setClients] = useState<OutsideClient[] | null>(null);
  const [busy, setBusy] = useState<OutsideClientKind | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => {
      void actions.outsideClients().then((found) => {
        if (live && found !== null) setClients(found);
      });
    };
    load();
    window.addEventListener("focus", load);
    return () => {
      live = false;
      window.removeEventListener("focus", load);
    };
  }, [actions]);
  const set = useCallback(
    async (kind: OutsideClientKind, access: OutsideAccess | null) => {
      setBusy(kind);
      const changed = await actions.setOutsideClient(kind, access);
      setBusy(null);
      if (changed !== null) {
        setClients((now) => now?.map((c) => (c.kind === kind ? changed : c)) ?? null);
      }
    },
    [actions],
  );
  return { clients, busy, set };
}
