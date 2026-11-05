import { createContext, use } from "react";
import type { Session } from "../../api/types.ts";
import type { Stopper } from "../../screens/chat/useStopTask.ts";

/** What a row leaves to the Mac app around it, in a pane there (B124). */
export interface RowsHost {
  messageAction: (action: "edit" | "rewind" | "fork", event: number) => void;
  openArtifact: (id: string, version: number) => void;
  runInTerminal: (command: string) => void;
  openImage: (id: string) => void;
}

/** What a chat's transcript rows need beyond their item. */
export interface ChatRows {
  // The chat the rows are in: their open state is kept under it.
  chat: string;
  session: Session | undefined;
  // Calls whose background task still runs.
  running: ReadonlySet<string>;
  // Subagents' streaming text, by the id of their Agent call.
  agentLive: Readonly<Record<string, string>>;
  // Null where nothing can be stopped, as in a read-only transcript.
  stopper: Stopper | null;
  openPixie: (id: string) => void;
  // A team's work in this chat, from its leader's call; only in a project chat (B70).
  openTeamWork: ((team: string) => void) | null;
  // A pixie's work in this chat, from its background result line (B112).
  openPixieWork: ((pixie: string) => void) | null;
  openChat: (id: string) => void;
  // Edit, Rewind and Fork for a user message by its event; null where none applies.
  messageActions: ((event: number) => MessageActions | null) | null;
  // The pane a shell command's Run in terminal runs from (its folder); null where it does not show.
  terminalPane: string | null;
  // The app around the rows; null in the desktop window, which does these itself.
  host: RowsHost | null;
}

export interface MessageActions {
  edit: (() => void) | null;
  rewind: (() => void) | null;
  fork: (() => void) | null;
}

const NONE: ChatRows = {
  chat: "",
  session: undefined,
  running: new Set(),
  agentLive: {},
  stopper: null,
  openPixie: () => undefined,
  openTeamWork: null,
  openPixieWork: null,
  openChat: () => undefined,
  messageActions: null,
  terminalPane: null,
  host: null,
};

export const RowsContext = createContext<ChatRows>(NONE);

export function useRows(): ChatRows {
  return use(RowsContext);
}
