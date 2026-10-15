import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type KeyboardEvent,
} from "react";
import type {
  Attachment,
  CreateSessionBody,
  Effort,
  MemoryScope,
  PermissionMode,
  Session,
  UpdateSessionBody,
} from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { draftKey, NO_DRAFT } from "../../store/state.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";
import { ConnectorsSheet, ResumeSheet, type ChatNav } from "./CommandSheets.tsx";
import { ContextMeter } from "./ContextMeter.tsx";
import { prepareImage } from "./images.ts";
import { localCommand, namedModel, type LocalCommand } from "./localCommands.ts";
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
import { Pending } from "./Pending.tsx";
import { PickerSheet } from "./PickerSheet.tsx";
import { Suggestions, type Suggestion } from "./Suggestions.tsx";
import { dropThumbnail, keepThumbnail, useThumbnail } from "./thumbnails.ts";
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

/**
 * What text starting with `!` or `#` is (B59), as in Claude Code: a shell command, a
 * memory, or (null) a message. `## ...` stays a Markdown heading.
 */
function modeOf(text: string, shell: boolean, memory: boolean): "bash" | "memory" | null {
  if (shell && text.startsWith("!")) return "bash";
  if (memory && text.startsWith("#") && !text.startsWith("##")) return "memory";
  return null;
}

export type NewChatPlace = Pick<CreateSessionBody, "mode" | "base" | "branch">;

type Props =
  | {
      session: Session;
      // Where `/resume` opens a chat (B59).
      nav: ChatNav;
      repo?: undefined;
      onCreated?: undefined;
      place?: undefined;
      pixie?: undefined;
      chat?: undefined;
    }
  | {
      session?: undefined;
      nav: ChatNav;
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
      nav?: undefined;
      session?: undefined;
      repo?: undefined;
      onCreated?: undefined;
      place?: undefined;
    };

/**
 * The message field with attachments and the quiet model, thinking and permission
 * selectors. In a new chat the first message creates the session with those choices.
 * While a turn runs, a message goes into it (B59) and waits above the composer until Claude
 * reads it at its next step, or for the turn to end when it cannot go in. Claude Code's
 * interactive commands (`/model`, `/permissions`, `/mcp`, `/resume`) open Nest's own
 * pickers and sheets instead of being sent (B59).
 */
export function Composer({ session, nav, repo, onCreated, place, pixie, chat }: Props) {
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
  const [sheet, setSheet] = useState<
    { kind: "mcp" } | { kind: "resume"; query: string } | { kind: "memory" } | null
  >(null);
  // Set when the last send was refused because Claude Code has the chat open.
  const [elsewhere, setElsewhere] = useState(false);
  const [draft, setDraft] = useState<Choices>({ model: null, effort: null, permission: null });
  const [caret, setCaret] = useState(0);
  const [focused, setFocused] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  // Where the caret goes once a completion is in the field.
  const caretAfter = useRef<number | null>(null);
  const project = session?.repo ?? repo ?? "";
  const suggest = useSuggestions({
    text,
    caret,
    focused,
    sessionId: live?.id,
    repo: project,
    filesOnly: pixie !== undefined,
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
  // A pixie's messages carry text only.
  const takesFiles = pixie === undefined && !closed;
  const context = session?.context ?? null;
  // A pixie's chats, and chats a pixie started, run no shell commands.
  const shellChat =
    session !== undefined && session.pixie_id == null && session.started_by_pixie === null
      ? session
      : undefined;
  const mode = modeOf(text, shellChat !== undefined, live !== undefined);
  const runs = shellChat === undefined ? [] : (state.bash[shellChat.id] ?? []);

  /** Sends to the open chat; while a turn runs it goes into that turn. */
  const deliver = async (id: string, prompt: string, ids: string[]) => {
    const result = await actions.send(id, prompt, ids);
    setElsewhere(result === "elsewhere");
    return result === "sent";
  };

  const runLocal = (command: LocalCommand) => {
    switch (command.name) {
      case "model": {
        const model = command.arg === "" ? null : namedModel(models ?? [], command.arg);
        if (model === null) setPicker("model");
        else pick("model", model);
        break;
      }
      case "permissions":
        setPicker("permission");
        break;
      case "mcp":
        setSheet({ kind: "mcp" });
        break;
      case "resume":
        setSheet({ kind: "resume", query: command.arg });
        break;
    }
  };

  /** Runs `typed` as one of Nest's own commands instead of sending it; false for others. */
  const ranLocally = (typed: string) => {
    const command = nav === undefined ? null : localCommand(typed);
    if (command === null) return false;
    setText("");
    runLocal(command);
    return true;
  };

  const choose = ({ result }: Suggestion) => {
    // Like Claude Code, choosing one of these runs it.
    if (ranLocally(result.text)) return;
    caretAfter.current = result.caret;
    setText(result.text);
    setCaret(result.caret);
  };

  /** Saves the `#` memory being typed; the composer clears once it is saved. */
  const remember = async (chatId: string, scope: MemoryScope) => {
    setSheet(null);
    const typed = text;
    const saved = await actions.remember(chatId, typed.slice(1).trim(), scope);
    if (saved !== null) actions.draftSent(key, typed, []);
  };

  const send = async () => {
    if (!canSend || ranLocally(text)) return;
    if (mode === "bash" && shellChat !== undefined) {
      const command = text.slice(1).trim();
      if (command === "") return;
      actions.draftSent(key, text, []);
      void actions.runShell(shellChat.id, command);
      return;
    }
    if (mode === "memory") {
      if (text.slice(1).trim() !== "") setSheet({ kind: "memory" });
      return;
    }
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
    // What `!` commands printed goes first, as Claude Code sends it; a slash command goes
    // as typed, and they wait for a message.
    const done = prompt.startsWith("/") ? [] : runs.filter((r) => r.result ?? r.error);
    const contexts = done.flatMap((r) => (r.result === null ? [] : [r.result.context]));
    const full = contexts.length === 0 ? prompt : `${contexts.join("\n")}\n\n${prompt}`;
    const ok = await deliver(session.id, full, ids);
    setSending(false);
    // By key: the user may have moved on to another chat meanwhile.
    if (ok) {
      actions.draftSent(key, typed, ids);
      ids.forEach(dropThumbnail);
      if (done.length > 0)
        actions.bashSent(
          session.id,
          done.map((r) => r.id),
        );
    }
  };

  /** Uploads chosen, pasted or dropped files; images get ready first (HEIC, size). */
  const addFiles = async (chosen: File[]) => {
    setUploads((n) => n + chosen.length);
    await Promise.all(
      chosen.map(async (file) => {
        const ready = await prepareImage(file);
        const uploaded = await actions.attachToDraft(key, ready);
        if (uploaded !== null) keepThumbnail(uploaded.id, ready);
        setUploads((n) => n - 1);
      }),
    );
  };

  const attach = async (event: ChangeEvent<HTMLInputElement>) => {
    const chosen = Array.from(event.target.files ?? []);
    event.target.value = "";
    await addFiles(chosen);
  };

  const dragOver = (event: DragEvent<HTMLDivElement>) => {
    if (takesFiles && event.dataTransfer.types.includes("Files")) event.preventDefault();
  };

  const drop = (event: DragEvent<HTMLDivElement>) => {
    if (!takesFiles) return;
    event.preventDefault();
    void addFiles(Array.from(event.dataTransfer.files));
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
      {live !== undefined && <Pending session={live} draft={key} />}
      {/* In the column just above the composer, like the background bar. */}
      {suggest.items.length > 0 && (
        <Suggestions
          label={suggest.label}
          items={suggest.items}
          active={suggest.active}
          onPick={choose}
        />
      )}
      <div
        className={mode === null ? "comp gl" : `comp gl ${mode}`}
        onDragOver={dragOver}
        onDrop={drop}
      >
        {mode === "bash" && (
          <p className="cmode">
            <b>Bash mode</b> Runs in the chat&apos;s folder
          </p>
        )}
        {mode === "memory" && (
          <p className="cmode">
            <b>Memory</b> Saved to CLAUDE.md, not sent
          </p>
        )}
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
              <AttachmentChip
                key={file.id}
                file={file}
                onRemove={() => {
                  actions.removeDraftFile(key, file.id);
                  dropThumbnail(file.id);
                }}
              />
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
          onPaste={(event) => {
            const pasted = pastedFiles(event.clipboardData);
            if (!takesFiles || pasted.length === 0) return;
            event.preventDefault();
            void addFiles(pasted);
          }}
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
              aria-label="Send"
              disabled={!canSend}
              onClick={() => void send()}
            >
              <Icon name="send" />
            </button>
          )}
        </div>
        {sheet?.kind === "memory" && live !== undefined && (
          <ActionSheet
            label="Save to memory"
            onClose={() => {
              setSheet(null);
            }}
          >
            {live.pixie_id == null && (
              <button
                className="asi"
                role="menuitem"
                onClick={() => void remember(live.id, "project")}
              >
                Project memory
                <small>CLAUDE.md in this project</small>
              </button>
            )}
            <button className="asi" role="menuitem" onClick={() => void remember(live.id, "user")}>
              User memory
              <small>Your CLAUDE.md, for all projects</small>
            </button>
          </ActionSheet>
        )}
        {sheet?.kind === "mcp" && (
          <ConnectorsSheet
            onClose={() => {
              setSheet(null);
            }}
          />
        )}
        {sheet?.kind === "resume" && nav !== undefined && (
          <ResumeSheet
            repo={project}
            current={session?.id}
            query={sheet.query}
            nav={nav}
            onClose={() => {
              setSheet(null);
            }}
          />
        )}
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

/**
 * The files on the clipboard. Safari on iPhone may list a pasted image among the items
 * only, so those are read when the file list is empty.
 */
function pastedFiles(data: DataTransfer): File[] {
  const files = Array.from(data.files);
  if (files.length > 0) return files;
  return Array.from(data.items).flatMap((item) => {
    const file = item.kind === "file" ? item.getAsFile() : null;
    return file === null ? [] : [file];
  });
}

/** An attached file: an image by its thumbnail, others by an icon, with its name. */
function AttachmentChip({ file, onRemove }: { file: Attachment; onRemove: () => void }) {
  const thumbnail = useThumbnail(file.id);
  return (
    <li className={thumbnail === null ? "chip" : "chip thumb"}>
      {thumbnail === null ? <Icon name="file" /> : <img src={thumbnail} alt={file.filename} />}
      <span>{file.filename}</span>
      <button aria-label={`Remove ${file.filename}`} onClick={onRemove}>
        <Icon name="x" />
      </button>
    </li>
  );
}
