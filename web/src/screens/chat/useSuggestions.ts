import { useEffect, useRef, useState } from "react";
import type { SlashCommand } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { availablePixies, availableTeams } from "../../store/selectors.ts";
import type { Suggestion } from "./Suggestions.tsx";
import { matchCommands, pixieMentions, replaceTrigger, soulLine, triggerAt } from "./suggest.ts";

// Typing pauses this long before the files are asked for.
const FILE_DELAY_MS = 150;

interface Input {
  text: string;
  caret: number;
  focused: boolean;
  // Undefined in a new chat: commands come from the project, and files are not offered.
  sessionId: string | undefined;
  // The project chat's repo, for the pixies and teams it can call (B40).
  repo: string;
}

/**
 * Completions for the composer: the chat's slash commands after a leading "/" (asked for
 * once per chat or project), and after an "@" the pixies and teams the chat can call, then
 * repo files (latest request wins).
 */
export function useSuggestions({ text, caret, focused, sessionId, repo }: Input) {
  const { state, actions } = useStore();
  const [commands, setCommands] = useState<Record<string, SlashCommand[]>>({});
  const requested = useRef(new Set<string>());
  const [found, setFound] = useState<string[]>([]);
  const [nav, setNav] = useState({ key: "", index: 0 });

  const trigger = focused ? triggerAt(text, caret) : null;
  const source = sessionId === undefined ? `repo:${repo}` : `session:${sessionId}`;
  const wantsCommands = trigger?.kind === "command";
  const fileQuery = trigger?.kind === "file" && sessionId !== undefined ? trigger.query : null;
  const mentioning = trigger?.kind === "file";
  const callable = mentioning ? availablePixies(state, repo) : [];
  const teams = mentioning ? availableTeams(state, repo) : [];
  // The first line of each callable pixie's soul, read once while mentioning.
  const [souls, setSouls] = useState<Record<string, string>>({});
  const asked = useRef(new Set<string>());
  const callableKey = callable.map((p) => p.id).join(" ");

  useEffect(() => {
    if (callableKey === "") return;
    for (const id of callableKey.split(" ")) {
      if (asked.current.has(id)) continue;
      asked.current.add(id);
      void actions.peekPixieFile(id, "soul").then((file) => {
        if (file !== null) setSouls((current) => ({ ...current, [id]: soulLine(file.text) }));
      });
    }
  }, [callableKey, actions]);

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
  } else if (trigger !== null) {
    // Pixies and teams are offered with or without files.
    const people = pixieMentions(teams, callable, souls, trigger.query);
    const files =
      fileQuery === null
        ? []
        : found.map((path) => ({
            key: path,
            label: path,
            hint: null,
            detail: null,
            group: "Files" as const,
            result: replaceTrigger(text, trigger, `@${path}`),
          }));
    items = [
      ...people.map((mention) => ({
        ...mention,
        result: replaceTrigger(text, trigger, `@${mention.handle}`),
      })),
      ...files,
    ];
  }
  const navKey = trigger === null ? "" : `${trigger.kind}:${trigger.query}`;
  const active = nav.key === navKey ? nav.index % items.length : 0;

  return {
    label: trigger?.kind === "file" ? mentionLabel(items) : "Commands",
    // Empty when nothing is being completed.
    items,
    active,
    move(delta: number) {
      setNav({ key: navKey, index: (active + delta + items.length) % items.length });
    },
  };
}

/** The list's name after an "@": what it holds. */
function mentionLabel(items: Suggestion[]): string {
  const files = items.some((item) => item.group === "Files");
  const pixies = items.some((item) => item.group === "Pixies");
  return pixies ? (files ? "Pixies and files" : "Pixies") : "Files";
}
