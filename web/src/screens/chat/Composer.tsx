import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from "react";
import type {
  CreateSessionBody,
  Effort,
  PermissionMode,
  Session,
  UpdateSessionBody,
} from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { draftKey, NO_DRAFT } from "../../store/state.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ContextMeter } from "./ContextMeter.tsx";
import {
  AGENT_DEFAULT,
  CLAUDE_DEFAULT,
  effortOptions,
  labelOf,
  modelOptions,
  NO_THINKING,
  permissionOptions,
  PICKER_TITLES,
  takesAuto,
  thinkingLevels,
  type Option,
  type PickerKind,
} from "./options.ts";
import { PickerSheet } from "./PickerSheet.tsx";
import { Suggestions, type Suggestion } from "./Suggestions.tsx";
import { useSuggestions } from "./useSuggestions.ts";

const BUSY = new Set<Session["state"]>(["starting", "running", "waiting"]);

/**
 * Whether Return adds a line: on a touch screen with no fine pointer and no hover, as a
 * phone's keyboard Return, while the Send button sends. With a mouse or trackpad around,
 * Enter sends, as on the Mac. A hardware keyboard on a phone alone cannot be told apart.
 */
function returnAddsLine(): boolean {
  const { matchMedia } = window as { matchMedia?: Window["matchMedia"] };
  return matchMedia?.("(any-pointer: fine), (any-hover: hover)").matches === false;
}

interface Choices {
  model: string | null;
  effort: Effort | null;
  permission: PermissionMode | null;
}

export type NewChatPlace = Pick<CreateSessionBody, "mode" | "base" | "branch">;

type Props =
  | {
      session: Session;
      repo?: undefined;
      onCreated?: undefined;
      place?: undefined;
      pixie?: undefined;
      chat?: undefined;
    }
  | {
      session?: undefined;
      repo: string;
      onCreated: (session: Session) => void;
      // Where the new chat works, as its place choice says (B55).
      place?: NewChatPlace;
      pixie?: undefined;
      chat?: undefined;
    }
  // A pixie's chat, if it has one yet: messages go through the pixie, which starts a new run
  // when needed. Its settings live on its page, so the selectors and suggestions stay out (D072).
  | {
      pixie: string;
      chat: Session | undefined;
      session?: undefined;
      repo?: undefined;
      onCreated?: undefined;
      place?: undefined;
    };

/**
 * The message field with attachments and the quiet model, thinking and permission
 * selectors. In a new chat the first message creates the session with those choices.
 * While a turn runs, a message is queued and sent when the turn ends.
 */
export function Composer({ session, repo, onCreated, place, pixie, chat }: Props) {
  const { state, actions } = useStore();
  // The message lives in the store, per chat, so it waits there while another chat is open.
  const key = draftKey(
    pixie !== undefined ? { pixie } : session === undefined ? { repo } : { session: session.id },
  );
  // The chat that runs: an open chat, or the pixie's.
  const live = session ?? chat;
  const { text, files } = state.drafts[key] ?? NO_DRAFT;
  const setText = (next: string) => {
    actions.setDraftText(key, next);
  };
  const [uploads, setUploads] = useState(0);
  const [sending, setSending] = useState(false);
  const [picker, setPicker] = useState<PickerKind | null>(null);
  // Set when the last send was refused because Claude Code has the chat open.
  const [elsewhere, setElsewhere] = useState(false);
  const [draft, setDraft] = useState<Choices>({ model: null, effort: null, permission: null });
  const [caret, setCaret] = useState(0);
  const [focused, setFocused] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  // Where the caret goes once a completion is in the field.
  const caretAfter = useRef<number | null>(null);
  const suggest = useSuggestions({
    text,
    caret,
    focused: focused && pixie === undefined,
    sessionId: session?.id,
    repo: session?.repo ?? repo ?? "",
  });

  useLayoutEffect(() => {
    const at = caretAfter.current;
    const el = field.current;
    if (at === null || el === null) return;
    caretAfter.current = null;
    el.focus();
    el.setSelectionRange(at, at);
  }, [text]);

  const models = state.models;
  const unknownModels = models === null;
  useEffect(() => {
    if (unknownModels) void actions.loadChoices();
  }, [unknownModels, actions]);

  const busy = live !== undefined && BUSY.has(live.state);
  const closed = session?.state === "closed";
  const choices: Choices =
    session === undefined
      ? draft
      : { model: session.model, effort: session.effort, permission: session.permission_mode };
  // The model the chat runs (or a new chat will run), for its thinking levels.
  const runModel = choices.model ?? (session === undefined ? state.agentDefaults?.model : null);
  const levels = thinkingLevels(models, runModel ?? null);
  const canSend = text.trim() !== "" && !sending && uploads === 0 && !closed;
  const context = session?.context ?? null;

  /** Sends to the open chat; the daemon queues it while a turn runs. */
  const deliver = async (id: string, prompt: string, ids: string[]) => {
    const result = await actions.send(id, prompt, ids);
    setElsewhere(result === "elsewhere");
    return result === "sent";
  };

  const choose = ({ result }: Suggestion) => {
    caretAfter.current = result.caret;
    setText(result.text);
    setCaret(result.caret);
  };

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    // As typed now: anything added while it sends stays in the draft.
    const typed = text;
    const prompt = text.trim();
    const ids = files.map((f) => f.id);
    if (pixie !== undefined) {
      const sent = (await actions.sendToPixie(pixie, prompt)) !== null;
      setSending(false);
      if (sent) actions.draftSent(key, typed, ids);
      return;
    }
    if (session === undefined) {
      const created = await actions.create({
        repo,
        prompt,
        attachment_ids: ids,
        ...(draft.model === null ? {} : { model: draft.model }),
        ...(draft.effort === null ? {} : { effort: draft.effort }),
        ...(draft.permission === null ? {} : { permission_mode: draft.permission }),
        ...place,
      });
      setSending(false);
      if (created === null) return;
      // Anything typed while it was created goes on in the new chat.
      actions.draftSent(key, typed, ids, draftKey({ session: created.id }));
      onCreated(created);
      return;
    }
    const ok = await deliver(session.id, prompt, ids);
    setSending(false);
    // By key: the user may have moved on to another chat meanwhile.
    if (ok) actions.draftSent(key, typed, ids);
  };

  const attach = async (event: ChangeEvent<HTMLInputElement>) => {
    const chosen = Array.from(event.target.files ?? []);
    event.target.value = "";
    setUploads((n) => n + chosen.length);
    await Promise.all(
      chosen.map(async (file) => {
        await actions.attachToDraft(key, file);
        setUploads((n) => n - 1);
      }),
    );
  };

  const optionsOf = (kind: PickerKind): Option<string>[] => {
    const listed: Record<PickerKind, Option<string>[]> = {
      model: modelOptions(models),
      effort: effortOptions(levels),
      permission: permissionOptions(models, runModel ?? null),
    };
    // An open chat offers no default option.
    return session === undefined ? [AGENT_DEFAULT, ...listed[kind]] : listed[kind];
  };

  // An open chat without a model runs Claude Code's default, so that entry is checked.
  const checked = (kind: PickerKind) =>
    kind === "model" && session !== undefined ? (choices.model ?? CLAUDE_DEFAULT) : choices[kind];

  const pick = (kind: PickerKind, value: string | null) => {
    if (session === undefined) {
      const next = { ...draft, [kind]: value };
      // A thinking level the newly chosen model does not take is dropped.
      const model = next.model ?? state.agentDefaults?.model ?? null;
      if (next.effort !== null && !thinkingLevels(models, model).includes(next.effort)) {
        next.effort = null;
      }
      // So is Auto, for a model that does not take it.
      if (next.permission === "auto" && !takesAuto(models, model)) next.permission = null;
      setDraft(next);
      return;
    }
    // New thinking applies from the next message.
    const body: Record<PickerKind, UpdateSessionBody> = {
      model: { model: String(value) },
      effort: { effort: value as Effort },
      permission: { permission_mode: value as PermissionMode },
    };
    void actions.update(session.id, body[kind]);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter picks a suggestion, and sends unless Return adds a line here.
    const enter = event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing;
    // Undefined while nothing is being completed.
    const active = suggest.items[suggest.active];
    if (active !== undefined && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      event.preventDefault();
      suggest.move(event.key === "ArrowDown" ? 1 : -1);
    } else if (active !== undefined && (enter || event.key === "Tab")) {
      event.preventDefault();
      choose(active);
    } else if (enter && !returnAddsLine()) {
      event.preventDefault();
      void send();
    }
  };

  const selector = (kind: PickerKind) => {
    const unavailable = kind === "effort" && levels.length === 0;
    const label = unavailable ? NO_THINKING : labelOf(kind, choices[kind], models);
    return (
      <button
        className="qt"
        aria-haspopup="dialog"
        aria-expanded={picker === kind}
        aria-label={`${PICKER_TITLES[kind]}: ${label}`}
        disabled={closed || unavailable}
        onClick={() => {
          setPicker(kind);
        }}
      >
        {label}
      </button>
    );
  };

  return (
    <>
      {/* In the column just above the composer, like the background bar. */}
      {suggest.items.length > 0 && (
        <Suggestions
          label={suggest.label}
          items={suggest.items}
          active={suggest.active}
          onPick={choose}
        />
      )}
      <div className="comp gl">
        {/* Always there, as VoiceOver often misses a live region inserted with its text. */}
        <div aria-live="polite">
          {elsewhere && (
            <p className="cnote">
              This chat is open in Claude Code right now. Close it there first.
            </p>
          )}
        </div>
        {files.length > 0 && (
          <ul className="atts" aria-label="Attachments">
            {files.map((file) => (
              <li key={file.id} className="chip">
                <Icon name="file" />
                <span>{file.filename}</span>
                <button
                  aria-label={`Remove ${file.filename}`}
                  onClick={() => {
                    actions.removeDraftFile(key, file.id);
                  }}
                >
                  <Icon name="x" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <label className="sr" htmlFor="composer">
          Message
        </label>
        <textarea
          id="composer"
          ref={field}
          rows={1}
          placeholder={closed ? "This chat is closed" : uploads > 0 ? "Uploading..." : "Message"}
          value={text}
          disabled={closed}
          onChange={(event) => {
            setText(event.target.value);
            setCaret(event.target.selectionStart);
          }}
          onSelect={(event) => {
            setCaret(event.currentTarget.selectionStart);
          }}
          onFocus={() => {
            setFocused(true);
          }}
          onBlur={() => {
            setFocused(false);
          }}
          onKeyDown={onKeyDown}
        />
        <div className="crow">
          {pixie === undefined && (
            <>
              <input
                ref={fileInput}
                type="file"
                multiple
                hidden
                aria-label="Attach files"
                onChange={(event) => void attach(event)}
              />
              <button
                className="qb"
                aria-label="Attach"
                disabled={closed}
                onClick={() => fileInput.current?.click()}
              >
                <Icon name="clip" />
              </button>
            </>
          )}
          <button
            className="qb"
            aria-label="Dictate"
            title="Use the keyboard's microphone to dictate"
            disabled={closed}
            onClick={() => field.current?.focus()}
          >
            <Icon name="mic" />
          </button>
          {pixie === undefined && (
            <>
              {selector("model")}
              {selector("effort")}
              {selector("permission")}
            </>
          )}
          {session !== undefined && context !== null && (
            <ContextMeter
              context={context}
              disabled={closed}
              onCompact={() => void deliver(session.id, "/compact", [])}
            />
          )}
          <span className="flex" />
          {busy && text.trim() === "" ? (
            <button
              className="send stop"
              aria-label="Interrupt"
              onClick={() => void actions.interrupt(live.id)}
            >
              <Icon name="stop" />
            </button>
          ) : (
            <button
              className="send"
              aria-label={busy ? "Queue" : "Send"}
              title={busy ? "Sends when Claude finishes" : undefined}
              disabled={!canSend}
              onClick={() => void send()}
            >
              <Icon name="send" />
            </button>
          )}
        </div>
        {picker !== null && (
          <PickerSheet
            title={PICKER_TITLES[picker]}
            options={optionsOf(picker)}
            value={checked(picker)}
            onPick={(value) => {
              pick(picker, value);
            }}
            onClose={() => {
              setPicker(null);
            }}
          />
        )}
      </div>
    </>
  );
}
