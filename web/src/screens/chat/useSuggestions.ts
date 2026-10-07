import { useEffect, useRef, useState } from "react";
import type { SlashCommand } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import type { Suggestion } from "./Suggestions.tsx";
import { matchCommands, replaceTrigger, triggerAt } from "./suggest.ts";

// Typing pauses this long before the files are asked for.
const FILE_DELAY_MS = 150;

interface Input {
  text: string;
  caret: number;
  focused: boolean;
  // Undefined in a new chat: commands come from the project, and files are not offered.
  sessionId: string | undefined;
  repo: string;
}

/**
 * Completions for the composer: the chat's slash commands after a leading "/" (asked for
 * once per chat or project), and repo files after an "@" (latest request wins).
 */
export function useSuggestions({ text, caret, focused, sessionId, repo }: Input) {
  const { actions } = useStore();
  const [commands, setCommands] = useState<Record<string, SlashCommand[]>>({});
  const requested = useRef(new Set<string>());
  const [found, setFound] = useState<string[]>([]);
  const [nav, setNav] = useState({ key: "", index: 0 });

  const trigger = focused ? triggerAt(text, caret) : null;
  const source = sessionId === undefined ? `repo:${repo}` : `session:${sessionId}`;
  const wantsCommands = trigger?.kind === "command";
  const fileQuery = trigger?.kind === "file" && sessionId !== undefined ? trigger.query : null;

  useEffect(() => {
    if (!wantsCommands || requested.current.has(source)) return;
    requested.current.add(source);
    const target = sessionId === undefined ? { repo } : { session: sessionId };
    void actions.commands(target).then((list) => {
      // A failure is asked again the next time a "/" starts the message.
      if (list === null) requested.current.delete(source);
      else setCommands((current) => ({ ...current, [source]: list.commands }));
    });
  }, [wantsCommands, source, sessionId, repo, actions]);

  useEffect(() => {
    // The query is null without a session; the check is for the type.
    if (fileQuery === null || sessionId === undefined) return;
    let latest = true;
    const timer = window.setTimeout(() => {
      void actions.files(sessionId, fileQuery).then((files) => {
        if (latest) setFound(files);
      });
    }, FILE_DELAY_MS);
    return () => {
      latest = false;
      window.clearTimeout(timer);
    };
  }, [fileQuery, sessionId, actions]);

  let items: Suggestion[] = [];
  if (trigger?.kind === "command") {
    items = matchCommands(commands[source] ?? [], trigger.query).map((c) => ({
      key: c.name,
      label: `/${c.name}`,
      hint: c.argument_hint,
      detail: c.description,
      result: replaceTrigger(text, trigger, `/${c.name}`),
    }));
  } else if (trigger !== null && fileQuery !== null) {
    items = found.map((path) => ({
      key: path,
      label: path,
      hint: null,
      detail: null,
      result: replaceTrigger(text, trigger, `@${path}`),
    }));
  }
  const navKey = trigger === null ? "" : `${trigger.kind}:${trigger.query}`;
  const active = nav.key === navKey ? nav.index % items.length : 0;

  return {
    label: trigger?.kind === "file" ? "Files" : "Commands",
    // Empty when nothing is being completed.
    items,
    active,
    move(delta: number) {
      setNav({ key: navKey, index: (active + delta + items.length) % items.length });
    },
  };
}
