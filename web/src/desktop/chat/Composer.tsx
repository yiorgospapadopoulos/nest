// A pane's composer, as the Mac's Composer.swift: an oval field with send (or stop) inside
// and under it a plain row with attach on the left (Linux has no dictation yet) and the
// quiet Model, Thinking and Permission menus and the context meter on the right. Slash
// commands, @ mentions and files list above the field; `/model` and `/permissions` open
// their list there. A new chat's first message starts it where its place picker says.
import {
  use,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type DragEvent,
  type KeyboardEvent,
} from "react";
import type {
  Attachment,
  Effort,
  LocalEngine,
  MemoryScope,
  PermissionMode,
  Session,
} from "../../api/types.ts";
import { localEngineName } from "../../screens/settings/accountText.ts";
import { useAutopilot } from "../../screens/chat/useAutopilot.ts";
import { prepareImage } from "../../screens/chat/images.ts";
import { localCommand, namedModel, type LocalCommand } from "../../screens/chat/localCommands.ts";
import { effortLabel, PERMISSIONS } from "../../screens/chat/options.ts";
import { placeName, sessionPlace } from "../../screens/chat/place.ts";
import { dropThumbnail, keepThumbnail, useThumbnail } from "../../screens/chat/thumbnails.ts";
import { useSuggestions } from "../../screens/chat/useSuggestions.ts";
import {
  choosingModel,
  CLAUDE,
  isSelected,
  modelLabel,
  supportsAuto,
  thinkingLevels,
  type NewChatChoices,
} from "../../store/catalog.ts";
import { useStore } from "../../store/context.ts";
import { repoNamed } from "../../store/general.ts";
import {
  localModelOf,
  NO_IMAGES,
  NO_WEB_SEARCH,
  weakBarText,
  weakWarning,
} from "../../store/local.ts";
import {
  catalogFor,
  chatModel,
  memberCall,
  memoryFile,
  modelSections,
  openingChoices,
  signInHint,
} from "../../store/selectors.ts";
import { draftKey, NO_DRAFT } from "../../store/state.ts";
import type { DraftModel } from "../layout/project.ts";
import { bashBlocks } from "../../transcript/build.ts";
import { tokens } from "../../format.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Sprite } from "../pixies/Sprite.tsx";
import { ShellContext } from "../shell/context.ts";
import { Button, TextField } from "../ui/controls.tsx";
import { Menu, QuietMenu } from "../ui/Menu.tsx";
import type { MenuEntry } from "../ui/menuItems.ts";
import { AutopilotButton } from "./Autopilot.tsx";
import { askRewindLast, onComposerFocus } from "./composerFocus.ts";
import { EscapeRepeat, keyAction, type ComposerKey } from "./composerKeys.ts";
import { useWholeItems } from "./wholeItems.ts";
import {
  contextLabel,
  HIGH_CONTEXT,
  shortEffort,
  shortModel,
  shortPermission,
  useFit,
} from "./fit.ts";
import { Glyph } from "./glyphs.tsx";
import { PendingMessages } from "./Bars.tsx";
import { PlaceButton } from "./WorkOn.tsx";
import { placeBody, selectedChoice, type NewChatChoice } from "./placePicker.ts";
import { Sheet } from "./Sheet.tsx";
import "./chat.css";

const IN_FLIGHT = new Set<Session["state"]>(["starting", "running", "waiting"]);

// What a local chat can do on each engine, under its name (LocalModelText.engineDetail).
const LOCAL_ENGINES: LocalEngine[] = ["claude", "codex"];
const LOCAL_ENGINE_DETAIL: Record<LocalEngine, string> = {
  claude: "Every Nest chat feature",
  codex: "Smaller tool set; no rewind or fork",
};

type Suggestion = ReturnType<typeof useSuggestions>["items"][number];

export type ComposerTarget =
  | { kind: "chat"; session: Session }
  // A new chat's pane, with where it works over the field; the empty workspace's composer
  // (`start`) has it in the row under the field (B90).
  | { kind: "start"; repo: string; onCreated: (session: Session) => void }
  | {
      kind: "draft";
      repo: string;
      place: NewChatChoice | null;
      model: DraftModel | null;
      onCreated: (session: Session) => void;
    }
  // A pixie's pane: messages go through the pixie, which starts its chat when it has none;
  // no attachments and no selectors, as the Mac's Composer(pixie:).
  | { kind: "pixie"; pixie: string; session: Session | undefined };

/** What text starting with `!` or `#` is (B59): a shell command, a memory, or a message. */
function modeOf(text: string, shell: boolean, memory: boolean): "bash" | "memory" | null {
  if (shell && text.startsWith("!")) return "bash";
  if (memory && text.startsWith("#") && !text.startsWith("##")) return "memory";
  return null;
}

/** The chat's last sent message, for Up in an empty field. */
function lastSent(
  events: { type: string; payload: Record<string, unknown> }[] | undefined,
): string | null {
  for (const event of [...(events ?? [])].reverse()) {
    if (event.type !== "session.user_message") continue;
    if (event.payload.origin !== undefined && event.payload.origin !== null) continue;
    const text = typeof event.payload.text === "string" ? bashBlocks(event.payload.text).rest : "";
    if (text.trim() !== "") return text;
  }
  return null;
}

interface Choices {
  provider: string;
  model: string | null;
  effort: Effort | null;
  permission: PermissionMode;
}

export function Composer({ target }: { target: ComposerTarget }) {
  const { state, actions } = useStore();
  const shell = use(ShellContext);
  const fit = useFit();
  const pixie = target.kind === "pixie" ? target.pixie : null;
  const session = target.kind === "chat" || target.kind === "pixie" ? target.session : undefined;
  const repoName =
    target.kind === "chat" || target.kind === "pixie" ? (session?.repo ?? "") : target.repo;
  const repo = repoNamed(state.repos, repoName);
  const key = draftKey(
    pixie !== null
      ? { pixie }
      : session === undefined
        ? { repo: repoName }
        : { session: session.id },
  );
  const { text, files } = state.drafts[key] ?? NO_DRAFT;
  const pilot = useAutopilot(session);
  const [refused, setRefused] = useState<string | null>(null);
  const [elsewhere, setElsewhere] = useState(false);
  const [uploads, setUploads] = useState(0);
  const [sending, setSending] = useState(false);
  const [picker, setPicker] = useState<"model" | "permissions" | null>(null);
  const [memory, setMemory] = useState(false);
  const [dropping, setDropping] = useState(false);
  const [draftChoices, setDraftChoices] = useState<NewChatChoices | null>(null);
  // This chat's own pick; without one it follows the project's selected place, live.
  const [place, setPlace] = useState<NewChatChoice | null>(
    target.kind === "draft" ? target.place : null,
  );
  const [branch, setBranch] = useState("");
  const [caret, setCaret] = useState(0);
  const [focused, setFocused] = useState(false);
  const [closedList, setClosedList] = useState<string | null>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const optionRow = useRef<HTMLDivElement>(null);
  useWholeItems(optionRow);
  const fileInput = useRef<HTMLInputElement>(null);
  const caretAfter = useRef<number | null>(null);
  const escapes = useRef(new EscapeRepeat());

  const setText = (next: string) => {
    setRefused(null);
    setElsewhere(false);
    actions.setDraftText(key, next);
  };

  useEffect(() => onComposerFocus(key, () => field.current?.focus()), [key]);

  // A new chat's pane takes the keyboard as it opens, as the Mac's draft.wantsFocus; after
  // whatever opened it (a menu, the palette, the tray) gave the focus back.
  const opensFocused = target.kind === "draft";
  useEffect(() => {
    if (!opensFocused) return;
    const timer = window.setTimeout(() => field.current?.focus(), 0);
    return () => {
      window.clearTimeout(timer);
    };
  }, [opensFocused]);

  useLayoutEffect(() => {
    const at = caretAfter.current;
    const el = field.current;
    if (at === null || el === null) return;
    caretAfter.current = null;
    el.focus();
    el.setSelectionRange(at, at);
  }, [text]);

  // Grows with its text up to 160 px, then scrolls.
  useLayoutEffect(() => {
    const el = field.current;
    if (el === null) return;
    el.style.height = "0px";
    el.style.height = `${String(Math.min(el.scrollHeight, 160))}px`;
  }, [text]);

  const unknownChoices = state.modelLists[CLAUDE] === undefined || state.agentDefaults === null;
  useEffect(() => {
    if (unknownChoices) void actions.loadChoices();
  }, [unknownChoices, actions]);

  const suggest = useSuggestions({ text, caret, focused, sessionId: session?.id, repo: repoName });
  const listKey = suggest.items.length === 0 ? null : `${suggest.label}:${text}:${String(caret)}`;
  const suggesting = suggest.items.length > 0 && closedList !== listKey && picker === null;

  const working = session !== undefined && IN_FLIGHT.has(session.state);
  const closed = session?.state === "closed";
  const choices: Choices | null =
    session === undefined
      ? (draftChoices ?? openingChoices(state, target.kind === "draft" ? target.model : null))
      : {
          provider: session.provider,
          model: chatModel(state, session),
          effort: session.effort,
          permission: session.permission_mode,
        };
  const catalog = catalogFor(state, choices?.provider);
  const levels = thinkingLevels(catalog, choices?.model ?? null);
  const localModel = localModelOf(state.local, choices?.model ?? null);
  const weak =
    target.kind === "start" || pixie !== null
      ? null
      : weakWarning(state.local, choices?.model ?? null);
  const member = memberCall(state, text);
  const shellChat =
    session !== undefined && session.pixie_id == null && session.started_by_pixie === null;
  const mode = modeOf(text, shellChat, session !== undefined);
  const runs = session === undefined || !shellChat ? [] : (state.bash[session.id] ?? []);
  const canSend = text.trim() !== "" && !sending && uploads === 0 && !closed && member === null;
  const hint =
    session === undefined && choices !== null ? signInHint(state, choices.provider) : null;

  const shownPlace: NewChatChoice =
    place ??
    selectedChoice(
      repo?.selected_place ?? null,
      pilot.on
        ? "worktree"
        : repo?.worktree.default === undefined || repo.worktree.default === null
          ? (state.agentDefaults?.mode ?? "in_place")
          : repo.worktree.default
            ? "worktree"
            : "in_place",
    );

  const pickModel = (model: string, provider: string) => {
    if (session !== undefined) {
      void actions.update(session.id, { model });
      return;
    }
    const defaults = state.agentDefaults;
    if (choices === null || defaults === null) return;
    setDraftChoices(choosingModel(choices, model, provider, catalogFor(state, provider), defaults));
  };
  const pickEffort = (effort: Effort) => {
    if (session !== undefined) void actions.update(session.id, { effort });
    else if (choices !== null) setDraftChoices({ ...choices, effort });
  };
  const pickPermission = (permission: PermissionMode) => {
    if (session !== undefined) void actions.update(session.id, { permission_mode: permission });
    else if (choices !== null) setDraftChoices({ ...choices, permission });
  };
  const permissions = PERMISSIONS.filter(
    (option) => option.value !== "auto" || supportsAuto(catalog, choices?.model ?? null),
  );

  const runLocal = (command: LocalCommand) => {
    switch (command.name) {
      case "model": {
        const model = command.arg === "" ? null : namedModel(catalog.models, command.arg);
        if (model === null) {
          if (command.arg === "") setPicker("model");
          else actions.toast(`No model named ${command.arg}`, "error");
        } else pickModel(model, choices?.provider ?? CLAUDE);
        break;
      }
      case "permissions":
        if (!pilot.on) setPicker("permissions");
        break;
      case "mcp":
        shell?.openSettings({ page: "configuration" });
        break;
      case "resume":
        if (command.arg === "") shell?.setPalette(true);
        else shell?.searchPalette(command.arg);
        break;
    }
  };

  const ranLocally = (typed: string) => {
    const command = localCommand(typed);
    if (command === null) return false;
    setText("");
    runLocal(command);
    return true;
  };

  const choose = ({ result }: Suggestion) => {
    if (ranLocally(result.text)) return;
    caretAfter.current = result.caret;
    setText(result.text);
    setCaret(result.caret);
  };

  const remember = async (scope: MemoryScope) => {
    if (session === undefined) return;
    setMemory(false);
    const typed = text;
    const saved = await actions.remember(session.id, typed.slice(1).trim(), scope);
    if (saved !== null) actions.draftSent(key, typed, []);
  };

  const send = async () => {
    if (!canSend || ranLocally(text)) return;
    if (mode === "bash" && session !== undefined) {
      const command = text.slice(1).trim();
      if (command === "") return;
      actions.draftSent(key, text, []);
      void actions.runShell(session.id, command);
      return;
    }
    if (mode === "memory") {
      if (text.slice(1).trim() === "") return;
      if (session?.pixie_id != null) void remember("user");
      else setMemory(true);
      return;
    }
    setSending(true);
    const typed = text;
    const prompt = text.trim();
    const ids = files.map((f) => f.id);
    if (target.kind === "pixie") {
      const sent = (await actions.sendToPixie(target.pixie, prompt)) !== null;
      setSending(false);
      if (sent) actions.draftSent(key, typed, []);
      return;
    }
    if (target.kind !== "chat") {
      const created = await actions.create({
        repo: target.repo,
        prompt,
        attachment_ids: ids,
        ...(choices === null
          ? {}
          : {
              provider: choices.provider,
              ...(choices.model === null ? {} : { model: choices.model }),
              ...(choices.effort === null ? {} : { effort: choices.effort }),
              permission_mode: choices.permission,
            }),
        ...pilot.create,
        ...(repo?.git === true ? placeBody(shownPlace, branch, repo) : {}),
      });
      setSending(false);
      if (created === null) return;
      actions.draftSent(key, typed, ids, draftKey({ session: created.id }));
      target.onCreated(created);
      return;
    }
    const chat = target.session;
    const done = prompt.startsWith("/") ? [] : runs.filter((r) => r.result ?? r.error);
    const contexts = done.flatMap((r) => (r.result === null ? [] : [r.result.context]));
    const full = contexts.length === 0 ? prompt : `${contexts.join("\n")}\n\n${prompt}`;
    const result = await actions.send(chat.id, full, ids);
    setSending(false);
    setElsewhere(result === "elsewhere");
    setRefused(typeof result === "object" ? result.refused : null);
    if (result === "sent") {
      actions.draftSent(key, typed, ids);
      ids.forEach(dropThumbnail);
      if (done.length > 0)
        actions.bashSent(
          chat.id,
          done.map((r) => r.id),
        );
    }
  };

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

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.nativeEvent.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
    const keys: Record<string, ComposerKey | undefined> = {
      Enter: event.shiftKey ? "shiftEnter" : "enter",
      ArrowUp: "up",
      ArrowDown: "down",
      Tab: event.shiftKey ? undefined : "tab",
      Escape: "escape",
    };
    const pressed = keys[event.key];
    if (pressed === undefined) return;
    const repeated =
      pressed === "escape" && !suggesting && !working && escapes.current.press(event.timeStamp);
    const action = keyAction(pressed, suggesting, text === "", working, repeated);
    const active = suggest.items[suggest.active];
    switch (action.kind) {
      case "move":
        suggest.move(action.delta);
        break;
      case "insert":
        if (active !== undefined) choose(active);
        break;
      case "close":
        setClosedList(listKey);
        break;
      case "send":
        void send();
        break;
      case "interrupt":
        if (session !== undefined) void actions.interrupt(session.id);
        break;
      case "recall": {
        const last = lastSent(state.transcripts[session?.id ?? ""]);
        if (last === null) return;
        caretAfter.current = last.length;
        setText(last);
        break;
      }
      case "rewind":
        if (session !== undefined) askRewindLast(session.id);
        break;
      case "ignore":
        return;
    }
    event.preventDefault();
    event.stopPropagation();
  };

  // A pixie's messages carry text only.
  const takesFiles = !closed && pixie === null;
  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const pasted = Array.from(event.clipboardData.files);
    if (!takesFiles || pasted.length === 0) return;
    event.preventDefault();
    void addFiles(pasted);
  };
  const onDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (takesFiles && event.dataTransfer.types.includes("Files")) {
      event.preventDefault();
      setDropping(true);
    }
  };
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    setDropping(false);
    if (!takesFiles || event.dataTransfer.files.length === 0) return;
    event.preventDefault();
    void addFiles(Array.from(event.dataTransfer.files));
  };

  const modelName = choices === null ? "Model" : modelLabel(catalog, choices.model);
  const effortName =
    levels.length === 0
      ? "No thinking"
      : choices?.effort == null
        ? "Thinking"
        : fit.compact
          ? shortEffort(choices.effort, effortLabel(choices.effort))
          : effortLabel(choices.effort);
  const shownPermission = pilot.on ? "bypassPermissions" : choices?.permission;
  const permissionLabel = PERMISSIONS.find((o) => o.value === shownPermission)?.label ?? "Ask";

  const modelEntries = (): MenuEntry[] => {
    const sections = modelSections(state, choices?.provider ?? null, session === undefined);
    const entries: MenuEntry[] = [];
    for (const section of sections) {
      if (entries.length > 0 && (section.local === true || section.engineLocal === true)) {
        entries.push({ type: "separator" });
      }
      entries.push({ type: "section", title: section.title });
      if (section.detail !== "") entries.push({ type: "note", text: section.detail });
      if (section.catalog.models.length === 0) {
        entries.push({ title: "Models unavailable", disabled: true, onSelect: () => undefined });
      }
      for (const option of section.catalog.models) {
        entries.push({
          title: option.display_name,
          detail: option.description,
          checked:
            section.provider === (choices?.provider ?? CLAUDE) &&
            isSelected(section.catalog, option, choices?.model ?? null),
          disabled: !section.available || section.unavailable?.includes(option.value) === true,
          warns: section.weak?.includes(option.value) === true,
          onSelect: () => {
            pickModel(option.value, section.provider);
          },
        });
      }
    }
    entries.push({ type: "separator" });
    // Which engine local chats run on, once there are local models (LocalMenuItems).
    const local = state.local.list;
    if (local !== null && local.models.length > 0) {
      entries.push({
        type: "submenu",
        title: `Local chats run on ${localEngineName(local.engine)}`,
        items: LOCAL_ENGINES.map((engine) => ({
          title: localEngineName(engine),
          detail: LOCAL_ENGINE_DETAIL[engine],
          checked: local.engine === engine,
          onSelect: () => {
            if (engine !== local.engine) void actions.setLocalEngine(engine);
          },
        })),
      });
    }
    entries.push({
      title: "Add local model…",
      onSelect: () => {
        shell?.openSettings({ page: "agents" });
      },
    });
    return entries;
  };

  const effortEntries = (): MenuEntry[] => [
    { type: "section", title: "Thinking" },
    ...(levels.length === 0
      ? [{ title: "Not available for this model", disabled: true, onSelect: () => undefined }]
      : levels.map((level) => ({
          title: effortLabel(level),
          checked: choices?.effort === level,
          onSelect: () => {
            pickEffort(level);
          },
        }))),
    ...(session !== undefined && levels.length > 0
      ? [
          { type: "separator" as const },
          { type: "note" as const, text: "Applies from your next message" },
        ]
      : []),
  ];

  const permissionEntries = (): MenuEntry[] => [
    { type: "section", title: "Permission mode" },
    ...permissions.map((option) => ({
      title: option.label,
      detail: option.hint ?? "",
      checked: choices?.permission === option.value,
      onSelect: () => {
        pickPermission(option.value);
      },
    })),
  ];

  const context = session?.context ?? null;
  const contextText = context === null ? null : contextLabel(fit.context, context);
  const chatPlace = session === undefined ? null : sessionPlace(session, repo);

  return (
    <div className={target.kind === "start" ? "dc-comp start" : "dc-comp"}>
      {session !== undefined && <PendingMessages session={session} draftKey={key} />}
      {(elsewhere || refused !== null || member !== null) && (
        <div className="dc-blocked" role="status">
          <Glyph name="warning" size={11} className="dc-wait" />
          <span>
            {elsewhere
              ? "This chat is open in Claude Code right now. Close it there first."
              : (member ?? refused)}
          </span>
          <button
            className="dc-xs"
            aria-label="Dismiss"
            onClick={() => {
              setElsewhere(false);
              setRefused(null);
            }}
          >
            <Glyph name="close" size={8} />
          </button>
        </div>
      )}
      {hint !== null && (
        <p className="dc-signin">
          <Glyph name="warning" size={10} className="dc-wait" />
          <span>{hint}</span>
        </p>
      )}
      {weak !== null && (
        <div className="dc-weak" role="group" aria-label="Weak at tools">
          <Glyph name="warning" size={10} className="dc-wait" />
          <span>{weakBarText(weak)}</span>
          <ChangeModelMenu
            session={session}
            kind="plain"
            onPick={pickModel}
            provider={choices?.provider ?? CLAUDE}
            model={choices?.model ?? null}
          />
          <Button
            kind="plain"
            onClick={() => {
              actions.dismissWeak(weak.id);
            }}
          >
            Don&apos;t show again
          </Button>
        </div>
      )}
      {picker !== null && choices !== null ? (
        <CommandPicker
          title={picker === "model" ? "Model" : "Permission mode"}
          choices={
            picker === "model"
              ? catalog.models.map((option) => ({
                  id: option.value,
                  title: option.display_name,
                  detail: option.description,
                  checked: isSelected(catalog, option, choices.model),
                  pick: () => {
                    pickModel(option.value, choices.provider);
                  },
                }))
              : permissions.map((option) => ({
                  id: option.value,
                  title: option.label,
                  detail: option.hint ?? "",
                  checked: option.value === choices.permission,
                  pick: () => {
                    pickPermission(option.value);
                  },
                }))
          }
          onClose={() => {
            setPicker(null);
            field.current?.focus();
          }}
        />
      ) : (
        suggesting && (
          <SuggestionList
            label={suggest.label}
            items={suggest.items}
            active={suggest.active}
            onPick={choose}
          />
        )
      )}
      {target.kind === "draft" && repo?.git === true && (
        <div className="dc-wcrow">
          <PlaceButton repo={repo} choice={shownPlace} onChoose={setPlace} quiet={false} />
          {shownPlace.kind === "newWorktree" && <BranchField value={branch} onChange={setBranch} />}
        </div>
      )}
      <div
        className={`dc-field${mode === "bash" ? " bash" : ""}${focused || dropping ? " focus" : ""}`}
        onDragOver={onDragOver}
        onDragLeave={() => {
          setDropping(false);
        }}
        onDrop={onDrop}
        onMouseDown={(event) => {
          if (event.target === event.currentTarget) {
            event.preventDefault();
            field.current?.focus();
          }
        }}
      >
        <div className="dc-fieldc">
          {mode !== null && (
            <span className={mode === "bash" ? "dc-mode bash" : "dc-mode"}>
              {mode === "bash"
                ? "! bash mode: runs in the chat's folder"
                : `# memory: saved to ${memoryFile(state, session?.provider)}`}
            </span>
          )}
          {files.length > 0 && (
            <div className="dc-atts" aria-label="Attachments" role="list">
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
            </div>
          )}
          <textarea
            ref={field}
            rows={1}
            aria-label="Message"
            placeholder={
              closed
                ? "This chat is closed"
                : target.kind === "start"
                  ? "Ask, build, / for commands, @ for references..."
                  : "Message"
            }
            value={text}
            disabled={closed}
            spellCheck
            onChange={(event: ChangeEvent<HTMLTextAreaElement>) => {
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
            onPaste={onPaste}
          />
          {uploads > 0 && (
            <span className="dc-fhint">
              <Fireflies size={9} />
              Uploading…
            </span>
          )}
        </div>
        <SendButton
          mode={working && text.trim() === "" ? "interrupt" : "send"}
          ready={canSend || sending}
          sending={sending}
          onSend={() => void send()}
          onInterrupt={() => {
            if (session !== undefined) void actions.interrupt(session.id);
          }}
        />
      </div>
      <div ref={optionRow} className="dc-crow">
        <input
          ref={fileInput}
          type="file"
          multiple
          hidden
          aria-label="Attach files"
          onChange={(event) => {
            const chosen = Array.from(event.target.files ?? []);
            event.target.value = "";
            void addFiles(chosen);
          }}
        />
        {pixie !== null ? null : localModel === null ? (
          <button
            className="dk-btn k-plain icon dc-attach"
            title="Attach"
            aria-label="Attach"
            disabled={closed}
            onClick={() => fileInput.current?.click()}
          >
            <Glyph name="plus" size={13} />
          </button>
        ) : (
          <Menu
            label="Attach"
            items={() => [
              { title: "Attach files…", onSelect: () => fileInput.current?.click() },
              ...(localModel.vision
                ? []
                : [
                    {
                      title: "Attach image",
                      detail: NO_IMAGES,
                      disabled: true,
                      onSelect: () => undefined,
                    },
                  ]),
              {
                title: "Web search",
                detail: NO_WEB_SEARCH,
                disabled: true,
                onSelect: () => undefined,
              },
            ]}
          >
            {(trigger) => (
              <button
                {...trigger}
                className="dk-btn k-plain icon dc-attach"
                title="Attach"
                aria-label="Attach"
              >
                <Glyph name="plus" size={13} />
              </button>
            )}
          </Menu>
        )}
        {(pixie === null || session !== undefined) && (
          <AutopilotButton control={pilot} disabled={closed} />
        )}
        {target.kind === "start" && repo?.git === true && (
          <span className="dc-startplace">
            <PlaceButton repo={repo} choice={shownPlace} onChoose={setPlace} quiet />
            {shownPlace.kind === "newWorktree" && (
              <BranchField value={branch} onChange={setBranch} />
            )}
          </span>
        )}
        {chatPlace !== null && (
          <span
            className="dc-place"
            title={
              chatPlace.kind === "worktree"
                ? `Worktree ${chatPlace.name}`
                : `Project folder, on ${placeName(chatPlace)}`
            }
            aria-label={
              chatPlace.kind === "worktree"
                ? `Worktree ${chatPlace.name}`
                : `On ${placeName(chatPlace)}`
            }
          >
            <Glyph name="branch" size={11} />
            {fit.showsPlaceName && <span>{placeName(chatPlace)}</span>}
          </span>
        )}
        <span className="grow" />
        {choices !== null && pixie === null && session?.pixie_id == null && (
          <>
            <QuietMenu
              title={fit.compact ? shortModel(modelName) : modelName}
              help="Model"
              items={modelEntries}
              align="end"
            />
            <span className="dc-dropi" data-drop="2">
              <QuietMenu
                title={effortName}
                help="Thinking"
                items={effortEntries}
                align="end"
                {...(levels.length === 0 && localModel !== null ? { tint: "var(--t3)" } : {})}
              />
            </span>
            <span className="dc-dropi" data-drop="3">
              <QuietMenu
                title={
                  fit.compact && shownPermission === "acceptEdits"
                    ? shortPermission(shownPermission, permissionLabel)
                    : permissionLabel
                }
                help="Permission mode"
                items={permissionEntries}
                align="end"
                disabled={pilot.on}
                {...(pilot.on
                  ? { tint: "var(--bad)" }
                  : target.kind === "start" && choices.permission === "bypassPermissions"
                    ? { tint: "var(--wait)" }
                    : {})}
              />
            </span>
          </>
        )}
        {session !== undefined && context !== null && contextText !== null && (
          <span className="dc-dropi" data-drop="1">
            <Menu
              label="Context"
              align="end"
              items={() => [
                {
                  type: "section",
                  title: `${tokens(context.used)} of ${tokens(context.limit)} tokens`,
                },
                {
                  title: "Compact",
                  onSelect: () => {
                    void actions.send(session.id, "/compact", []);
                  },
                },
              ]}
            >
              {(trigger) => (
                <button
                  {...trigger}
                  className={context.percent > HIGH_CONTEXT ? "dc-ctx high" : "dc-ctx"}
                  title={`Context window: ${tokens(context.used)} of ${tokens(context.limit)} tokens`}
                  aria-label={`Context ${String(Math.round(context.percent))} percent`}
                >
                  {contextText}
                </button>
              )}
            </Menu>
          </span>
        )}
      </div>
      {memory && session !== undefined && (
        <Sheet
          title="Save to memory"
          onClose={() => {
            setMemory(false);
          }}
          width={380}
        >
          <p className="dc-alert">{`“${text.slice(1).trim()}” goes into ${memoryFile(state, session.provider)}: the project's, or yours for all projects.`}</p>
          <div className="dc-sheet-acts">
            <Button
              onClick={() => {
                setMemory(false);
              }}
            >
              Cancel
            </Button>
            <Button onClick={() => void remember("user")}>User memory</Button>
            <Button kind="primary" data-autofocus onClick={() => void remember("project")}>
              Project memory
            </Button>
          </div>
        </Sheet>
      )}
    </div>
  );
}

/** A new worktree's optional branch name: a quiet mono capsule the size of the selector. */
function BranchField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <TextField
      className="dc-branchf"
      label="Branch name, optional"
      title="A name for the worktree's branch; left empty, Nest names it"
      placeholder="Branch name (optional)"
      mono
      value={value}
      onChange={onChange}
    />
  );
}

/** A round button inside the field: the accent once there is something to send; a stop while it works. */
function SendButton({
  mode,
  ready,
  sending,
  onSend,
  onInterrupt,
}: {
  mode: "send" | "interrupt";
  ready: boolean;
  sending: boolean;
  onSend: () => void;
  onInterrupt: () => void;
}) {
  if (mode === "interrupt") {
    return (
      <button
        className="dc-send stop"
        title="Interrupt (Esc)"
        aria-label="Interrupt"
        onClick={onInterrupt}
      >
        <Glyph name="stop" size={9} />
      </button>
    );
  }
  return (
    <button
      className={ready ? "dc-send ready" : "dc-send"}
      title="Send"
      aria-label="Send"
      disabled={!ready}
      onClick={onSend}
    >
      {sending ? <Fireflies size={10} /> : <Glyph name="send" size={13} />}
    </button>
  );
}

function AttachmentChip({ file, onRemove }: { file: Attachment; onRemove: () => void }) {
  const thumbnail = useThumbnail(file.id);
  const remove = (
    <button className="dc-xs" aria-label={`Remove ${file.filename}`} onClick={onRemove}>
      <Glyph name="close" size={8} />
    </button>
  );
  if (thumbnail !== null) {
    return (
      <span className="dc-imgchip" role="listitem" title={file.filename}>
        <img src={thumbnail} alt={file.filename} />
        {remove}
      </span>
    );
  }
  return (
    <span className="dc-chip att" role="listitem">
      <Glyph name="attach" size={10} />
      <span>{file.filename}</span>
      {remove}
    </span>
  );
}

interface Choice {
  id: string;
  title: string;
  detail: string;
  checked: boolean;
  pick: () => void;
}

/** What `/model` or `/permissions` opens above the composer, as Claude Code's own pickers. */
function CommandPicker({
  title,
  choices,
  onClose,
}: {
  title: string;
  choices: Choice[];
  onClose: () => void;
}) {
  return (
    <div className="dc-picklist" role="listbox" aria-label={title}>
      <div className="dc-pickh">
        <span>{title}</span>
        <button className="dc-xs" aria-label="Close" onClick={onClose}>
          <Glyph name="close" size={8} />
        </button>
      </div>
      {choices.length === 0 && <p className="dc-quiet pad">Models unavailable</p>}
      {choices.map((choice) => (
        <button
          key={choice.id}
          role="option"
          aria-selected={choice.checked}
          className={choice.checked ? "dc-sugi on" : "dc-sugi"}
          onClick={() => {
            choice.pick();
            onClose();
          }}
        >
          <Glyph name="check" size={9} className={choice.checked ? "dc-ck" : "dc-ck off"} />
          <span className="dc-sugl">{choice.title}</span>
          <span className="dc-sugd">{choice.detail}</span>
        </button>
      ))}
    </div>
  );
}

// Keeps the focus, and the caret, in the message field while choosing.
const keepFocus = (event: { preventDefault: () => void }) => {
  event.preventDefault();
};

/** Slash commands, or pixies, teams and files for the token at the caret, above the field. */
function SuggestionList({
  label,
  items,
  active,
  onPick,
}: {
  label: string;
  items: Suggestion[];
  active: number;
  onPick: (item: Suggestion) => void;
}) {
  const list = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [active]);
  const files = label !== "Commands";
  const row = (item: Suggestion) => {
    const index = items.indexOf(item);
    return (
      <button
        key={item.key}
        role="option"
        tabIndex={-1}
        aria-selected={index === active}
        className={index === active ? "dc-sugi on" : "dc-sugi"}
        onPointerDown={keepFocus}
        onMouseDown={keepFocus}
        onClick={() => {
          onPick(item);
        }}
      >
        {item.mascots !== undefined ? (
          <span className="dc-sugm" aria-hidden="true">
            {item.mascots.slice(0, 4).map((m, at) => (
              <Sprite
                key={at}
                mascot={m.mascot}
                color={m.color}
                size={item.mascots?.length === 1 ? 13 : 11}
              />
            ))}
          </span>
        ) : (
          files && <Glyph name="file" size={10} className="dc-t3" />
        )}
        <span className={files && item.group === "Files" ? "dc-sugl mono" : "dc-sugl"}>
          {item.label}
        </span>
        {item.hint !== null && <span className="dc-sugh">{item.hint}</span>}
        {item.detail !== null && <span className="dc-sugd">{item.detail}</span>}
      </button>
    );
  };
  const groups = (["Pixies", "Files"] as const).flatMap((group) => {
    const members = items.filter((item) => item.group === group);
    return members.length === 0 ? [] : [{ group, members }];
  });
  return (
    <div className="dc-picklist" role="listbox" aria-label={label} ref={list}>
      {groups.length === 0 ? (
        <>
          <div className="dc-pickh">
            <span>{label}</span>
          </div>
          <div className="dc-sugs">{items.map(row)}</div>
        </>
      ) : (
        <div className="dc-sugs">
          {groups.map(({ group, members }) => (
            <div key={group} role="group" aria-label={group}>
              <div className="dc-pickh sec">
                <span>{group}</span>
              </div>
              {members.map(row)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** "Change model" as a button that opens the chat's model list, for a local chat's bars. */
export function ChangeModelMenu({
  session,
  kind = "soft",
  onPick,
  provider,
  model,
}: {
  session: Session | undefined;
  kind?: "soft" | "plain";
  // A new chat's choice; an open chat's model changes on the chat.
  onPick?: (model: string, provider: string) => void;
  provider?: string;
  model?: string | null;
}) {
  const { state, actions } = useStore();
  const own = provider ?? session?.provider ?? CLAUDE;
  const current = model ?? (session === undefined ? null : chatModel(state, session));
  return (
    <Menu
      label="Change model"
      items={() =>
        modelSections(state, own, session === undefined).flatMap((section): MenuEntry[] => [
          { type: "section", title: section.title },
          ...section.catalog.models.map((option) => ({
            title: option.display_name,
            detail: option.description,
            checked: section.provider === own && isSelected(section.catalog, option, current),
            disabled: !section.available || section.unavailable?.includes(option.value) === true,
            onSelect: () => {
              if (onPick !== undefined) onPick(option.value, section.provider);
              else if (session !== undefined)
                void actions.update(session.id, { model: option.value });
            },
          })),
        ])
      }
    >
      {(trigger) => (
        <button {...trigger} className={`dk-btn k-${kind}`}>
          Change model
        </button>
      )}
    </Menu>
  );
}
