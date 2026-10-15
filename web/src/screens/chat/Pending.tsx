import { useState } from "react";
import type { QueuedMessage, Session } from "../../api/types.ts";
import { asDraftFiles } from "../../store/actions.ts";
import { useStore } from "../../store/context.ts";
import { bashBlocks } from "../../transcript/build.ts";
import { Icon } from "../../ui/Icon.tsx";
import { usePrefill } from "./usePrefill.tsx";

const WORKING = new Set<Session["state"]>(["starting", "running", "waiting"]);

const NONE: QueuedMessage[] = [];

interface Props {
  session: Session;
  // The composer's draft, where an edited message goes back.
  draft: string;
}

/** When a pending message reaches Claude, in a line. */
function when(message: QueuedMessage, working: boolean): string {
  if (message.sent) return "Claude reads this at its next step";
  return working ? "Sends when this turn ends" : "Waiting";
}

/**
 * Messages sent while Claude works that it has not read yet (B59), above the composer as in
 * Claude's apps: each can be sent now (stopping the turn), edited or removed. Once Claude
 * reads one, it shows in the transcript where it read it.
 */
export function Pending({ session, draft }: Props) {
  const { state, actions } = useStore();
  const messages = state.queued[session.id] ?? NONE;
  // Send now was tapped: until the next list arrives, as the message moves.
  const [sending, setSending] = useState<{ list: QueuedMessage[]; ids: string[] }>({
    list: messages,
    ids: [],
  });
  const tapped = sending.list === messages ? sending.ids : [];
  const { fill, ask } = usePrefill(draft);
  const working = WORKING.has(session.state);

  const sendNow = async (id: string) => {
    setSending({ list: messages, ids: [...tapped, id] });
    if (!(await actions.sendNow(session.id, id))) {
      setSending((s) => ({ ...s, ids: s.ids.filter((x) => x !== id) }));
    }
  };

  const edit = async (message: QueuedMessage) => {
    if ((await actions.cancelQueued(session.id, message.id)) !== "removed") return;
    // What `!` commands printed stays out: it was for Claude (B59).
    fill({ text: bashBlocks(message.text).rest, files: asDraftFiles(message.attachments) });
  };

  return (
    <>
      {messages.length > 0 && (
        <ul className="pend" aria-label="Pending messages">
          {messages.map((message) => (
            <li key={message.id} className="pm gl">
              <div className="pmt">
                <Text text={message.text} />
                {message.attachments.length > 0 && (
                  <small>{message.attachments.map((a) => a.filename).join(", ")}</small>
                )}
                <small className="pmw">{when(message, working)}</small>
              </div>
              <button
                className="pmb"
                disabled={tapped.includes(message.id)}
                onClick={() => void sendNow(message.id)}
              >
                Send now
              </button>
              <button
                className="pmi"
                aria-label="Edit pending message"
                onClick={() => void edit(message)}
              >
                <Icon name="edit" />
              </button>
              <button
                className="pmi"
                aria-label="Remove pending message"
                onClick={() => void actions.cancelQueued(session.id, message.id)}
              >
                <Icon name="x" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {ask}
    </>
  );
}

/** A pending message's text, with the `!` commands it carries as their command lines. */
function Text({ text }: { text: string }) {
  const { commands, rest } = bashBlocks(text);
  return (
    <>
      {commands.length > 0 && (
        <small className="pmc">{commands.map((c) => `! ${c.command}`).join("  ")}</small>
      )}
      <span>{rest}</span>
    </>
  );
}
