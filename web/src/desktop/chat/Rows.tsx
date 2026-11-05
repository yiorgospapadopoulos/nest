// A chat's transcript rows (TranscriptRow and the
// rows it switches to): the user's accent bubble with its actions on hover, the reply as
// text with Copy on hover, quiet lines for thinking, tools, hooks and notes that open in
// place, pixie calls, and the approvals answered where they ask.
import { use, useEffect, useMemo, useState, type ReactNode } from "react";
import type { GroupEntry, Pixie, PixieTeam, TeamMember } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import {
  summarizeTools,
  thoughtLabel,
  toolKind,
  type ToolKind,
} from "../../transcript/activity.ts";
import type {
  AutopilotReportItem,
  DecisionItem,
  HookItem,
  PixieCallItem,
  PixieResultItem,
  ResultImage,
  SentFile,
  SubStep,
  ThinkingItem,
  ToolItem,
  TranscriptItem,
} from "../../transcript/build.ts";
import type { EditDiff } from "../../transcript/edits.ts";
import type { GitHubPart } from "../../transcript/github.ts";
import { mentionColors, mentionParts } from "../../transcript/mentions.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Markdown } from "../../ui/Markdown.tsx";
import { terminalLine } from "../layout/tools.ts";
import { Sprite, TeamFace } from "../pixies/Sprite.tsx";
import { useBridge } from "../context.ts";
import { ShellContext } from "../shell/context.ts";
import { runInTerminal } from "../shell/frame/terminal.ts";
import { Menu } from "../ui/Menu.tsx";
import type { MenuEntry } from "../ui/menuItems.ts";
import { ApprovalCard } from "./ApprovalCard.tsx";
import { AutopilotReportCard, DecisionLine } from "./Autopilot.tsx";
import { DiffCounts } from "./bits.tsx";
import { ArtifactCard } from "./ArtifactCard.tsx";
import { groupRow, setOpen, useOpen, useTurnShown } from "./expanded.ts";
import { Disclosure, Glyph, type GlyphName } from "./glyphs.tsx";
import { useImage } from "./images.ts";
import { PixieCard } from "./PixieCards.tsx";
import { collapsedOutput, diffHunks, latestLine } from "./rowText.ts";
import { useRows, type MessageActions } from "./rowsContext.ts";
import { segments } from "./segments.ts";
import { ImageSheet, Sent } from "./ImageSheet.tsx";
import "./chat.css";

const KIND_GLYPHS: Record<ToolKind, GlyphName> = {
  command: "terminal",
  read: "doc",
  edit: "pencil",
  search: "search",
  fetch: "globe",
  agent: "agent",
  other: "wrench",
};

const ARTIFACT_NAMES = new Set(["Save artifact", "Update artifact"]);

function glyphOf(name: string): GlyphName {
  return ARTIFACT_NAMES.has(name) ? "doc" : KIND_GLYPHS[toolKind(name)];
}

/** A tool's name as its row shows it: a pixie call reads as Claude's own agent call. */
function toolName(name: string): string {
  return toolKind(name) === "agent" && name.startsWith("mcp__") ? "Agent" : name;
}

/** One transcript item; the event key (`data-ev`) lets a search hit find it. */
export function TranscriptRow({ item }: { item: TranscriptItem }) {
  const ev = item.key.replace(/\..*$/, "");
  switch (item.kind) {
    case "user":
      return (
        <div className="dc-urow" data-ev={ev}>
          {item.from !== undefined && <FromPixie id={item.from} />}
          <UserBubble
            text={item.text}
            attachments={item.attachments}
            github={item.github}
            event={Number(item.key)}
          />
        </div>
      );
    case "answer":
      return (
        <div className="dc-urow dc-answer" data-ev={ev}>
          <span className="dc-aq">{item.question}</span>
          <UserBubble text={item.text} attachments={[]} event={null} />
        </div>
      );
    case "assistant":
      return (
        <div data-ev={ev}>
          <AssistantText text={item.text} />
        </div>
      );
    case "thinking":
      return <ThinkingRow item={item} ev={ev} />;
    case "tool":
      return <ToolRow item={item} ev={ev} />;
    case "tools":
      return <ToolGroupRow items={item.items} id={item.key} ev={ev} />;
    case "hook":
      return <HookRow item={item} ev={ev} />;
    case "bash":
      return <BashRow id={item.key} command={item.command} output={item.output} ev={ev} />;
    case "system":
      return <SystemLine text={item.text} ev={ev} />;
    case "turn":
      return <TurnEndLine id={item.key} text={item.text} ev={ev} />;
    case "report":
      return <NoteRow title={item.title} text={item.text} ev={ev} />;
    case "pixie_result":
      return <PixieResultRow item={item} ev={ev} />;
    case "decision":
      return <DecisionRow item={item} ev={ev} />;
    case "autopilot_report":
      return <ReportRow item={item} ev={ev} />;
    case "pixie":
      return <PixieCallRow item={item} ev={ev} />;
    case "approval":
      return (
        <div data-ev={ev}>
          <ApprovalCard approval={item.approval} style="inline" />
        </div>
      );
    case "artifact":
      return <ArtifactCard item={item} ev={ev} />;
    case "card":
      return <PixieCard item={item} ev={ev} />;
  }
}

/** A quiet centred line: a note, a failure, a resolved approval. */
export function SystemLine({ text, ev }: { text: string; ev?: string }) {
  return (
    <p className="dc-sys" data-ev={ev}>
      {text}
    </p>
  );
}

/** A Copy button over the content's top trailing corner while the pointer is over it. */
export function HoverCopy({
  text,
  children,
  className,
}: {
  text: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className === undefined ? "dc-hcopy" : `dc-hcopy ${className}`}>
      {children}
      <CopyButton text={text} />
    </div>
  );
}

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const bridge = useBridge();
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!done) return;
    const timer = window.setTimeout(() => {
      setDone(false);
    }, 1200);
    return () => {
      window.clearTimeout(timer);
    };
  }, [done]);
  return (
    <button
      className="dc-copy dk-btn k-plain icon"
      title={label}
      aria-label={label}
      onClick={() => {
        void (bridge.pane?.({ kind: "copy", text }) ?? navigator.clipboard.writeText(text)).then(
          () => {
            setDone(true);
          },
        );
      }}
    >
      <Glyph name={done ? "check" : "copy"} size={11} />
    </button>
  );
}

/** "from Scout" with its mascot, above a message the pixie sent. */
function FromPixie({ id }: { id: string }) {
  const { state } = useStore();
  const pixie = state.pixies[id];
  return (
    <div className="dc-from">
      {pixie !== undefined && <Sprite mascot={pixie.mascot} color={pixie.color} size={11} />}
      <span>{pixie === undefined ? "from a pixie" : `from ${pixie.name}`}</span>
    </div>
  );
}

interface BubbleProps {
  text: string;
  attachments: SentFile[];
  github?: GitHubPart | undefined;
  // The message's event, for Edit, Rewind and Fork; null for an answer.
  event: number | null;
}

/** The solid accent bubble (B80), its mentions semibold, with its actions on hover. */
function UserBubble({ text, attachments, github, event }: BubbleProps) {
  const { state } = useStore();
  const rows = useRows();
  const colors = useMemo(
    () => mentionColors(state.pixies, state.teams),
    [state.pixies, state.teams],
  );
  const actions =
    event === null || Number.isNaN(event) ? null : (rows.messageActions?.(event) ?? null);
  const hasText = text !== "" || github !== undefined;
  return (
    <div className="dc-ucol">
      {attachments.length > 0 &&
        (hasText ? (
          <Sent files={attachments} />
        ) : (
          <div className="dc-ubub-w">
            {actions !== null && <MessageActionsMenu actions={actions} />}
            <Sent files={attachments} />
          </div>
        ))}
      {hasText && (
        <div className="dc-ubub-w">
          {actions !== null && <MessageActionsMenu actions={actions} />}
          <div className="dc-ubub">
            {mentionParts(text, colors).map((part, index) =>
              part.color === null ? part.text : <b key={index}>{part.text}</b>,
            )}
            {github !== undefined && <GitHubText part={github} after={text !== ""} />}
          </div>
        </div>
      )}
    </div>
  );
}

/** Nest's part of a bubble from GitHub (B101): a grey first line, the issue or comments. */
function GitHubText({ part, after }: { part: GitHubPart; after: boolean }) {
  return (
    <span className={after ? "dc-gh after" : "dc-gh"}>
      <span className="dc-ghq">{part.header}</span>
      {part.kind === "issue" ? (
        <>
          <span className="dc-ght">{part.title}</span>
          {part.excerpt !== "" && <span className="dc-ghx">{part.excerpt}</span>}
          {part.comments !== null && <span className="dc-ghq">{part.comments}</span>}
        </>
      ) : (
        part.items.map((item, index) => (
          <span key={index} className="dc-ghi">
            {item.place !== "" && <span className="dc-ghq mono">{item.place}</span>}
            <span>{item.text}</span>
          </span>
        ))
      )}
    </span>
  );
}

/** The "..." beside a user message: Edit, Rewind and Fork from here, while no turn runs (B59). */
function MessageActionsMenu({ actions }: { actions: MessageActions }) {
  const entries = (): MenuEntry[] => [
    ...(actions.edit === null
      ? []
      : [{ title: "Edit", icon: "edit" as const, onSelect: actions.edit }]),
    ...(actions.rewind === null
      ? []
      : [{ title: "Rewind…", icon: "rewind" as const, onSelect: actions.rewind }]),
    ...(actions.fork === null
      ? []
      : [{ title: "Fork from here", icon: "fork" as const, onSelect: actions.fork }]),
  ];
  return (
    <Menu label="Message actions" items={entries} align="end">
      {(trigger, open) => (
        <button
          {...trigger}
          className={open ? "dc-mact open" : "dc-mact"}
          title="Edit, rewind or fork from this message"
          aria-label="Message actions"
        >
          <Glyph name="more" size={13} />
        </button>
      )}
    </Menu>
  );
}

/** A reply: its shell commands in blocks of their own with Copy, the rest as text. */
export function AssistantText({ text, copyable = true }: { text: string; copyable?: boolean }) {
  const parts = useMemo(() => segments(text), [text]);
  const body = parts.some((part) => part.kind === "command") ? (
    <div className="dc-segs">
      {parts.map((part, index) =>
        part.kind === "markdown" ? (
          <div key={index} className="dc-md">
            <Markdown text={part.text} />
          </div>
        ) : (
          <CommandBlock key={index} command={part.text} />
        ),
      )}
    </div>
  ) : (
    <div className="dc-md">
      <Markdown text={text} />
    </div>
  );
  return copyable ? <HoverCopy text={text}>{body}</HoverCopy> : body;
}

/** A shell command from a reply in mono, with Copy and, for one line, Run in terminal. */
function CommandBlock({ command }: { command: string }) {
  const { state, actions } = useStore();
  const { terminalPane, host } = useRows();
  const shell = use(ShellContext);
  // A command of several lines would run line by line; Copy still offers it.
  const runs = terminalLine(command) !== null;
  return (
    <div className="dc-cmd">
      <code>{command}</code>
      <CopyButton text={command} label="Copy the command" />
      {runs && (host !== null || (shell?.project != null && terminalPane !== null)) && (
        <button
          className="dc-copy dk-btn k-plain icon"
          title="Run the command in a terminal pane in the chat's folder"
          aria-label="Run in terminal"
          onClick={() => {
            if (host !== null) {
              host.runInTerminal(command);
              return;
            }
            if (shell === null || terminalPane === null) return;
            runInTerminal(
              shell,
              { sessions: state.sessions, claudeChats: state.claudeChats, repos: state.repos },
              command,
              terminalPane,
              (text) => {
                actions.toast(text, "error");
              },
            );
          }}
        >
          <Glyph name="terminal" size={11} />
        </button>
      )}
    </div>
  );
}

/** "Thought for 8s" and a chevron, opening to the thinking in muted italics. */
function ThinkingRow({ item, ev }: { item: ThinkingItem; ev: string }) {
  const { chat } = useRows();
  const [open, toggle] = useOpen(chat, item.key);
  const expandable = item.text.trim() !== "";
  return (
    <div className="dc-think" data-ev={ev}>
      <button
        className="dc-line quiet"
        disabled={!expandable}
        aria-expanded={expandable ? open : undefined}
        onClick={toggle}
      >
        <span>{thoughtLabel(item.ms)}</span>
        {expandable && <Disclosure open={open} />}
      </button>
      {open && expandable && <p className="dc-thought">{item.text}</p>}
    </div>
  );
}

/** "Ran 3 commands, read 2 files", shimmering while any runs; opens to the calls. */
function ToolGroupRow({
  items,
  id,
  ev,
}: {
  items: (ToolItem | ThinkingItem)[];
  id: string;
  ev: string;
}) {
  const { chat, running } = useRows();
  const tools = items.filter((item): item is ToolItem => item.kind === "tool");
  const summary = summarizeTools(tools, running);
  const first = tools[0];
  const row = groupRow(id);
  // A lone agent opened while it ran as a row stays open once it folds to this line.
  const call = tools.length === 1 && first !== undefined ? first.key : row;
  const [opened] = useOpen(chat, row);
  const [kept] = useOpen(chat, call);
  const open = opened || kept;
  const toggle = () => {
    setOpen(chat, row, !open);
    if (open) setOpen(chat, call, false);
  };
  return (
    <div className="dc-group" data-ev={ev}>
      <button className="dc-line" aria-expanded={open} onClick={toggle}>
        <Glyph
          name={first === undefined ? "wrench" : glyphOf(first.name)}
          size={11}
          className="dc-ti"
        />
        <span className={summary.running ? "dc-gsum dc-shimmer" : "dc-gsum"}>{summary.text}</span>
        {summary.failed > 0 && <span className="dc-bad">{`${String(summary.failed)} failed`}</span>}
        <Disclosure open={open} />
      </button>
      {open && (
        <div className="dc-gitems">
          {items.map((child) =>
            child.kind === "tool" ? (
              <ToolRow key={child.key} item={child} ev={child.key.replace(/\..*$/, "")} />
            ) : (
              <ThinkingRow key={child.key} item={child} ev={child.key.replace(/\..*$/, "")} />
            ),
          )}
        </div>
      )}
    </div>
  );
}

/**
 * A tool call: its icon, name, argument and result note; it opens to its output, or for
 * an agent call to what its subagent did and is doing. An edit shows its diff.
 */
function ToolRow({ item, ev }: { item: ToolItem; ev: string }) {
  const { chat, agentLive, running, stopper } = useRows();
  const [open, toggle] = useOpen(chat, item.key);
  const kind = toolKind(item.name);
  const agent = kind === "agent";
  const live = agent ? (agentLive[item.id] ?? "") : "";
  const steps = item.steps ?? [];
  const output = item.detail?.replace(/^\n+|\n+$/g, "") ?? "";
  const diff = item.diff;
  const busy = item.result === null || running.has(item.id);
  const expandable =
    diff === undefined && (output !== "" || (agent && (steps.length > 0 || live !== "")));
  const note = item.result ?? "running";
  const preview = !open && agent ? latestLine(live) : null;
  return (
    <div className="dc-tool" data-ev={ev}>
      <div
        className={expandable ? "dc-line tool open-able" : "dc-line tool"}
        role={expandable ? "button" : undefined}
        tabIndex={expandable ? 0 : undefined}
        aria-expanded={expandable ? open : undefined}
        onClick={expandable ? toggle : undefined}
        onKeyDown={
          expandable
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  toggle();
                }
              }
            : undefined
        }
      >
        <Glyph name={glyphOf(item.name)} size={11} className="dc-ti" />
        <span className="dc-tn">{toolName(item.name)}</span>
        {item.arg !== "" && (
          <span className={kind === "read" || kind === "edit" ? "dc-ta link" : "dc-ta"}>
            {item.arg}
          </span>
        )}
        {diff !== undefined ? (
          <DiffCounts added={diff.added} removed={diff.removed} />
        ) : kind === "edit" && note === "done" ? (
          <Glyph name="check" size={10} className="dc-ok" />
        ) : note !== "" ? (
          <span className={item.failed ? "dc-tr bad" : busy ? "dc-tr dc-shimmer" : "dc-tr"}>
            {item.failed ? note : `· ${note}`}
          </span>
        ) : null}
        {expandable && <Disclosure open={open} />}
        {agent && busy && stopper?.offered(item.id) === true && (
          <StopTaskButton id={item.id} name={item.arg || item.name} />
        )}
      </div>
      {open && agent && <AgentSteps steps={steps} live={live} running={busy} />}
      {preview !== null && <p className="dc-live">{preview}</p>}
      {diff !== undefined ? (
        <EditDiffView id={item.key} diff={diff} path={item.arg} />
      ) : (
        open && output !== "" && <ToolOutput id={item.key} output={output} />
      )}
      {diff !== undefined && item.failed && output !== "" && (
        <ToolOutput id={item.key} output={output} />
      )}
      {item.images !== undefined && <ToolImages images={item.images} />}
    </div>
  );
}

/** The small stop square of a running subagent, call or background task (B59). */
export function StopTaskButton({ id, name }: { id: string; name: string }) {
  const { stopper } = useRows();
  if (stopper?.offered(id) !== true) return null;
  return (
    <button
      className="dc-stop dk-btn k-plain icon"
      title={`Stop ${name}`}
      aria-label={`Stop ${name}`}
      disabled={stopper.stopping(id)}
      onClick={(event) => {
        event.stopPropagation();
        stopper.stop(id);
      }}
    >
      <Glyph name="stop" size={9} />
    </button>
  );
}

/** An edit's change under its call: removed lines in red, added in green, folded when long. */
function EditDiffView({ id, diff, path }: { id: string; diff: EditDiff; path: string }) {
  const { chat } = useRows();
  const [all, toggle] = useOpen(chat, `${id}-diff`);
  const { hunks, more } = diffHunks(diff.lines, all);
  return (
    <div
      className="dc-diff"
      role="group"
      aria-label={`Changes to ${path}: ${String(diff.added)} added, ${String(diff.removed)} removed`}
    >
      {hunks.map((hunk, index) => (
        <div key={index}>
          {index > 0 && <div className="dc-dgap">⋯</div>}
          {hunk.map((line, at) => (
            <div key={at} className={`dc-dl ${line.kind}`}>
              <span className="dc-dm">
                {line.kind === "add" ? "+" : line.kind === "del" ? "-" : " "}
              </span>
              <span className="dc-dt">{line.text === "" ? " " : line.text}</span>
            </div>
          ))}
        </div>
      ))}
      {more !== null && (
        <button className="dc-more" onClick={toggle}>
          {all ? "Show less" : more}
        </button>
      )}
    </div>
  );
}

/** A tool's output, whole when short, else its first lines with Show more; Copy on hover. */
export function ToolOutput({ id, output }: { id: string; output: string }) {
  const { chat } = useRows();
  const [all, toggle] = useOpen(chat, `${id}-all`);
  const collapsed = useMemo(() => collapsedOutput(output), [output]);
  return (
    <HoverCopy text={output} className="dc-out">
      <pre>{all ? output : collapsed.preview}</pre>
      {collapsed.more !== null && (
        <button className="dc-more" onClick={toggle}>
          {all ? "Show less" : collapsed.more}
        </button>
      )}
    </HoverCopy>
  );
}

function DecisionRow({ item, ev }: { item: DecisionItem; ev: string }) {
  const { chat } = useRows();
  return <DecisionLine decision={item.decision} chat={chat} id={item.key} ev={ev} />;
}

function ReportRow({ item, ev }: { item: AutopilotReportItem; ev: string }) {
  const { chat } = useRows();
  return <AutopilotReportCard report={item.report} chat={chat} id={item.key} ev={ev} />;
}

/** A hook's muted line, opening to its output; a failure is tinted and opens by default. */
function HookRow({ item, ev }: { item: HookItem; ev: string }) {
  const { chat } = useRows();
  const [flipped, toggle] = useOpen(chat, item.key);
  const failure = item.tone === "error";
  const open = item.detail !== null && failure !== flipped;
  return (
    <div className={failure ? "dc-hook bad" : "dc-hook"} data-ev={ev}>
      <button
        className="dc-line quiet"
        disabled={item.detail === null}
        aria-expanded={item.detail === null ? undefined : open}
        onClick={toggle}
      >
        <Glyph name={failure ? "warning" : "hook"} size={11} className="dc-ti" />
        <span className={open ? "dc-hookt wrap" : "dc-hookt"}>{item.text}</span>
        {item.detail !== null && <Disclosure open={open} />}
      </button>
      {open && item.detail !== null && <ToolOutput id={item.key} output={item.detail} />}
    </div>
  );
}

interface BashProps {
  id: string;
  command: string;
  output: string;
  notes?: string[];
  running?: boolean;
  failure?: string | null;
  ev?: string;
}

/** A `!` command the user ran: the command in mono, its output folded, notes (B59). */
export function BashRow({
  id,
  command,
  output,
  notes = [],
  running = false,
  failure = null,
  ev,
}: BashProps) {
  const trimmed = output.replace(/^\n+|\n+$/g, "");
  return (
    <div className="dc-bash" data-ev={ev} aria-label={`Shell command: ${command}`} role="group">
      <div className="dc-line">
        <span className="dc-bang">!</span>
        <code className="dc-bc">{command}</code>
        {running && <Fireflies size={9} />}
        {notes.map((note) => (
          <span key={note} className="dc-tr">{`· ${note}`}</span>
        ))}
      </div>
      {trimmed !== "" && <ToolOutput id={id} output={trimmed} />}
      {failure !== null && <p className="dc-bfail">{failure}</p>}
    </div>
  );
}

/** "Worked for 1m 12s" under a turn, shown while its reply is hovered; it keeps its height. */
function TurnEndLine({ id, text, ev }: { id: string; text: string; ev: string }) {
  const shown = useTurnShown(id);
  return (
    <p className={shown ? "dc-turn shown" : "dc-turn"} data-ev={ev}>
      {text}
    </p>
  );
}

/** Nest's own messages: a report that chats finished, a habit's report, a limit resume. */
function NoteRow({ title, text, ev }: { title: string | undefined; text: string; ev: string }) {
  if (title === undefined) {
    return (
      <div className="dc-note col" data-ev={ev}>
        <span className="dc-noteh">
          <Glyph name="checklist" size={10} />
          Chats you started finished
        </span>
        <span className="dc-notet">{text}</span>
      </div>
    );
  }
  const habit = title === "Habit report";
  return (
    <div className="dc-note" data-ev={ev}>
      <Glyph name={habit ? "bell" : "playCircle"} size={10} />
      <span className="dc-noteh">{habit ? "Habit report" : "Resumed after the limit"}</span>
      <span className="dc-notet clamp">{text}</span>
    </div>
  );
}

const RESULT_WORDS: Record<PixieResultItem["status"], string> = {
  done: "finished",
  failed: "failed",
  stopped: "was stopped",
  interrupted: "was interrupted",
};
const RESULT_GLYPHS: Record<PixieResultItem["status"], GlyphName> = {
  done: "checkCircle",
  failed: "alertCircle",
  stopped: "stopCircle",
  interrupted: "pause",
};

/** "@tester finished": a background pixie call's end (B112), opening its work. */
function PixieResultRow({ item, ev }: { item: PixieResultItem; ev: string }) {
  const { state } = useStore();
  const { openPixieWork } = useRows();
  const slug = state.pixies[item.pixieId]?.slug;
  const text = `${slug === undefined ? "A pixie" : `@${slug}`} ${RESULT_WORDS[item.status]}`;
  const body = (
    <>
      <Glyph name={RESULT_GLYPHS[item.status]} size={10} />
      <span className="dc-noteh">{text}</span>
    </>
  );
  return openPixieWork === null ? (
    <div className="dc-note" data-ev={ev}>
      {body}
    </div>
  ) : (
    <button
      className="dc-note link"
      data-ev={ev}
      onClick={() => {
        openPixieWork(item.pixieId);
      }}
    >
      {body}
    </button>
  );
}

/** The team a call goes to when it calls the team's leader, where teams' calls show (B70). */
function teamOf(teams: Record<string, PixieTeam>, pixie: Pixie): PixieTeam | null {
  return Object.values(teams).find((t) => t.leader_id === pixie.id) ?? null;
}

/** A team's members for its mark: its leader and members at work hop while the call runs. */
function teamFaces(
  team: PixieTeam,
  pixies: Record<string, Pixie>,
  group: GroupEntry[] | undefined,
  busy: boolean,
): TeamMember[] {
  const entry = group?.find((e) => e.team_id === team.id);
  return Object.values(pixies)
    .filter((p) => p.team_id === team.id)
    .map((p) => {
      const leader = p.id === team.leader_id;
      const working = entry?.members.some((m) => m.pixie_id === p.id && m.state === "running");
      return {
        pixie_id: p.id,
        leader,
        state: busy && (leader || working === true) ? "running" : null,
      };
    });
}

/**
 * A pixie's call (B40): its mascot and name open the pixie; the rest of the row opens in
 * place to the call's steps and answer, shimmering while it runs. In a project chat a
 * team leader's call is the team's (B70): its grid and name open the team's work.
 */
function PixieCallRow({ item, ev }: { item: PixieCallItem; ev: string }) {
  const { state } = useStore();
  const { chat, running, agentLive, openPixie, openTeamWork } = useRows();
  const [open, toggle] = useOpen(chat, item.key);
  const { pixie, call, steps } = item;
  const busy = call.result === null || running.has(call.id);
  const team = openTeamWork === null ? null : teamOf(state.teams, pixie);
  const name = team?.name ?? pixie.name;
  const live = agentLive[call.id] ?? "";
  const preview = open ? null : latestLine(live);
  return (
    <div className="dc-pxcall" data-ev={ev}>
      <div className="dc-line">
        <button
          className="dc-pxwho"
          title={team === null ? `Open ${name} in Pixies` : `Open ${name}'s work in this chat`}
          aria-label={team === null ? `Open ${name}` : `Open ${name}${busy ? " working" : ""}`}
          onClick={() => {
            if (team !== null) openTeamWork?.(team.id);
            else openPixie(pixie.id);
          }}
        >
          {team === null ? (
            <>
              <Sprite
                mascot={pixie.mascot}
                color={pixie.color}
                size={13}
                working={busy}
                phaseKey={pixie.id}
              />
              <span className="dc-tn">{pixie.name}</span>
            </>
          ) : (
            <>
              <TeamFace
                members={teamFaces(team, state.pixies, state.pixieGroups[chat], busy)}
                pixies={state.pixies}
                className="dc-team"
                size={6}
              />
              <span className="dc-tn" style={{ color: pixie.color }}>
                {team.name}
              </span>
              {busy && <span className="dc-tr plain">working</span>}
            </>
          )}
        </button>
        <button className="dc-pxtask" aria-expanded={open} onClick={toggle}>
          <span className={busy ? "dc-ta plain dc-shimmer" : "dc-ta plain"}>{call.arg}</span>
          {!(team !== null && busy) && (
            <span className={call.failed ? "dc-tr bad" : "dc-tr"}>
              {call.failed ? call.result : `· ${call.result ?? "running"}`}
            </span>
          )}
          <Disclosure open={open} />
        </button>
        {busy && <StopTaskButton id={call.id} name={name} />}
      </div>
      {open && (
        <AgentSteps steps={steps} live={live} running={busy} pixie={{ answer: call.detail }} />
      )}
      {preview !== null && <p className="dc-live">{preview}</p>}
    </div>
  );
}

/**
 * An opened agent or pixie call: its subagent's thinking, text and tools in order, what
 * it is writing now, then (for a pixie) its answer, along a thin line.
 */
function AgentSteps({
  steps,
  live,
  running,
  pixie,
}: {
  steps: SubStep[];
  live: string;
  running: boolean;
  // A pixie's call ends in its answer; a subagent's shows as its call's output.
  pixie?: { answer: string | null };
}) {
  return (
    <div className="dc-steps">
      {steps.map((step) => {
        switch (step.kind) {
          case "thinking":
            return (
              <p key={step.key} className="dc-thought">
                {step.text}
              </p>
            );
          case "text":
            return <AssistantText key={step.key} text={step.text} copyable={false} />;
          case "call":
            return (
              <div key={step.key} className="dc-step">
                <Glyph name={glyphOf(step.text.split(" ")[0] ?? "")} size={10} />
                <span>{step.text}</span>
              </div>
            );
          case "images":
            return <ToolImages key={step.key} images={step.images} indent={false} />;
        }
      })}
      {live !== "" && <AssistantText text={live} copyable={false} />}
      {pixie !== undefined &&
        (pixie.answer !== null && pixie.answer !== "" ? (
          <AssistantText text={pixie.answer} />
        ) : (
          steps.length === 0 &&
          live === "" && (
            <span className="dc-quiet">
              {running ? "Starting..." : "Stopped before it answered"}
            </span>
          )
        ))}
    </div>
  );
}

/** A tool result's images as thumbnails; a click opens one full size (B59). */
function ToolImages({ images, indent = true }: { images: ResultImage[]; indent?: boolean }) {
  return (
    <div className={indent ? "dc-imgs" : "dc-imgs flush"}>
      {images.map((image, index) => (
        <Thumbnail key={`${image.id}.${String(index)}`} id={image.id} />
      ))}
    </div>
  );
}

function Thumbnail({ id }: { id: string }) {
  const { host } = useRows();
  const url = useImage(id);
  const [open, setOpen] = useState(false);
  if (url === undefined) return <Fireflies size={10} />;
  if (url === null) return <span className="dc-quiet">Image not available</span>;
  return (
    <>
      <button
        className="dc-thumb"
        title="Open full size"
        aria-label="Image from the tool"
        onClick={() => {
          if (host === null) setOpen(true);
          else host.openImage(id);
        }}
      >
        <img src={url} alt="" />
      </button>
      {open && (
        <ImageSheet
          url={url}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </>
  );
}
