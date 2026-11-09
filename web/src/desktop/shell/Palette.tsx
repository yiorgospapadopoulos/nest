import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { SearchHitKind } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { draftKey } from "../../store/state.ts";
import { chatStatus, needsCount, pendingFor, type Tone } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon, type IconName } from "../../ui/Icon.tsx";
import {
  catalog,
  defaultEditorName,
  move,
  palette,
  search,
  searchesMessages,
  sections,
  selected,
  showMessages,
  visible,
  type PaletteAction,
  type PaletteItem,
} from "../layout/palette.ts";
import { focusComposer } from "../chat/composerFocus.ts";
import { useShell } from "./context.ts";
import { claudePane } from "./panes.ts";

const optionId = (index: number) => `dk-palette-${String(index)}`;

// Matched words come wrapped in [[ and ]]; the palette shows them in bold, as the Mac's.
const plain = (snippet: string) => snippet.replaceAll("[[", "").replaceAll("]]", "");
function Snippet({ text }: { text: string }) {
  return text
    .split(/(\[\[.*?\]\])/)
    .map((part, index) => (part.startsWith("[[") ? <b key={index}>{part.slice(2, -2)}</b> : part));
}

// What a search hit's row shows: the hit's kind and its text.
interface Hit {
  kind: SearchHitKind;
  snippet: string;
  title: string;
  repo: string;
}

// The Mac's glyphs (PaletteView.swift) that the shared icon set lacks, on its 24 point grid.
const EXTRA = {
  globe: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5c2.4 2.4 3.5 5.2 3.5 8.5s-1.1 6.1-3.5 8.5c-2.4-2.4-3.5-5.2-3.5-8.5s1.1-6.1 3.5-8.5z" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </>
  ),
  board: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M9.5 4.5v15M15 4.5v15" />
    </>
  ),
  workspace: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M12 4.5v15M12 12h8.5" />
    </>
  ),
  left: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M9 4.5v15" />
    </>
  ),
  right: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M15 4.5v15" />
    </>
  ),
  wrench: (
    <path d="M14.5 4.5a4.5 4.5 0 0 0-4.3 5.9L4.5 16.1a1.9 1.9 0 0 0 2.7 2.7l5.7-5.7a4.5 4.5 0 0 0 5.9-4.3l-2.6 2.6-2.4-.6-.6-2.4z" />
  ),
} satisfies Record<string, ReactNode>;
type GlyphName = IconName | keyof typeof EXTRA;
const isExtra = (name: GlyphName): name is keyof typeof EXTRA => name in EXTRA;

function Glyph({ name }: { name: GlyphName }) {
  if (isExtra(name)) {
    return (
      <svg className="ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        {EXTRA[name]}
      </svg>
    );
  }
  return <Icon name={name} />;
}

const HIT_GLYPHS: Record<SearchHitKind, GlyphName> = {
  title: "chat",
  user: "user",
  assistant: "spark",
  tool: "wrench",
  tool_result: "lines",
  claude_chat: "term",
  codex_chat: "term",
};

/** A row's glyph, as the Mac's PaletteGlyph: a chat's status, else its action's symbol. */
function ItemGlyph({ item, tone, hit }: { item: PaletteItem; tone: Tone | null; hit?: Hit }) {
  const action = item.action;
  if ("openChat" in action) return tone === null ? <Glyph name="folder" /> : <Dot tone={tone} />;
  if ("openMessage" in action)
    return <Glyph name={hit === undefined ? "chat" : HIT_GLYPHS[hit.kind]} />;
  if ("newChat" in action) return <Glyph name="plus" />;
  if ("newTerminal" in action) return <Glyph name="term" />;
  if ("newBrowser" in action) return <Glyph name="globe" />;
  if ("showView" in action) {
    return <Glyph name={action.showView === "artifacts" ? "doc" : action.showView} />;
  }
  if ("toggleSidebar" in action) return <Glyph name="left" />;
  if ("toggleActivity" in action) return <Glyph name="right" />;
  if ("showUsage" in action) return <Glyph name="clock" />;
  if ("openInEditor" in action) return <Glyph name="code" />;
  return <Glyph name="folder" />;
}

/** The Ctrl K palette (layout/palette.ts): chats, commands, projects, then messages. */
export function Palette() {
  const { state, actions } = useStore();
  const shell = useShell();
  // Built once when the palette opens, as the Mac's, with any search it opens with.
  const [p, setP] = useState(() =>
    search(
      palette(
        catalog({
          open: shell.desk.tabs.open,
          current: shell.project,
          chats: Object.values(state.sessions)
            .filter((s) => s.archived_at === null && s.pixie_id == null)
            .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
            .map((s) => ({
              id: s.id,
              title: s.title,
              project: s.repo,
              status: chatStatus(s, pendingFor(state, s.id)).label,
            })),
          view: shell.state.view,
          leftCollapsed: shell.state.leftCollapsed,
          rightCollapsed: shell.state.rightCollapsed,
          editor: defaultEditorName(shell.editors),
          attention: (project) => needsCount(state, project),
        }),
      ),
      shell.paletteSearch,
    ),
  );
  const list = useRef<HTMLDivElement>(null);
  // Each search hit's kind and text, by its action.
  const [hits, setHits] = useState<ReadonlyMap<string, Hit>>(() => new Map());

  const query = p.query;
  const searching = searchesMessages(p);
  useEffect(() => {
    if (!searching) return;
    const timer = window.setTimeout(() => {
      void actions.search(query.trim()).then((results) => {
        if (results === null) return;
        const kinds = new Map<string, Hit>();
        const found: PaletteItem[] = results.hits.map((hit) => {
          const item: PaletteItem = {
            group: "Messages",
            title: hit.title,
            subtitle: `${hit.repo} · ${plain(hit.snippet)}`,
            action: {
              openMessage:
                hit.kind === "claude_chat" || hit.kind === "codex_chat"
                  ? claudePane(hit.session_id)
                  : hit.session_id,
              project: hit.repo,
              event: hit.event_id,
            },
          };
          kinds.set(JSON.stringify(item.action), {
            kind: hit.kind,
            snippet: hit.snippet,
            title: hit.title,
            repo: hit.repo,
          });
          return item;
        });
        setHits(kinds);
        setP((current) => showMessages(current, query, found));
      });
    }, 200);
    return () => {
      window.clearTimeout(timer);
    };
  }, [query, searching, actions]);

  const run = (action: PaletteAction) => {
    shell.setPalette(false);
    // A chat opened from here takes the keyboard, as one opened from its row has it there.
    if ("openChat" in action) {
      shell.openChat(action.openChat);
      focusComposer(draftKey({ session: action.openChat }));
    } else if ("openMessage" in action) {
      if (action.event === null) shell.openPane(action.openMessage);
      else shell.openChat(action.openMessage, action.event);
      focusComposer(draftKey({ session: action.openMessage }));
    } else if ("newChat" in action) shell.newChat();
    else if ("newTerminal" in action) shell.newTerminal();
    else if ("newBrowser" in action) shell.newBrowser();
    else if ("showView" in action) shell.setView(action.showView);
    else if ("toggleSidebar" in action) shell.toggleSidebar();
    else if ("toggleActivity" in action) shell.toggleActivity();
    else if ("showUsage" in action) shell.openSettings({ page: "usage" });
    else if ("openInEditor" in action) shell.openIn("editor");
    else shell.selectTab(action.goToProject);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setP(move(p, event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const item = selected(p);
      if (item !== null) run(item.action);
    } else if (event.key === "Escape") {
      event.preventDefault();
      shell.setPalette(false);
    }
  };

  useEffect(() => {
    list.current?.querySelector(".on")?.scrollIntoView({ block: "nearest" });
  }, [p.selection]);

  const shown = visible(p);
  return createPortal(
    <div
      className="dk-overlay dk-palo"
      onMouseDown={() => {
        shell.setPalette(false);
      }}
    >
      <div
        className="dk-palette"
        role="dialog"
        aria-label="Search chats and commands"
        onMouseDown={(event) => {
          event.stopPropagation();
        }}
      >
        <label className="dk-pfield">
          <Icon name="search" />
          <input
            autoFocus
            placeholder="Search chats and messages, or run a command"
            aria-label="Search chats, messages and commands"
            role="combobox"
            aria-expanded="true"
            aria-controls="dk-palette-list"
            // Focus stays in the field; a screen reader follows the highlighted row.
            aria-activedescendant={selected(p) === null ? undefined : optionId(p.selection)}
            value={p.query}
            onChange={(event) => {
              setP(search(p, event.target.value));
            }}
            onKeyDown={onKeyDown}
          />
        </label>
        <div
          className="dk-plist"
          id="dk-palette-list"
          // A listbox holds options only; "No matches" is a plain note in its place.
          role={shown.length === 0 ? undefined : "listbox"}
          ref={list}
        >
          {shown.length === 0 && <p className="dk-empty">No matches</p>}
          {sections(shown).map((section) => (
            <div key={section.start} role="group" aria-label={section.group}>
              <h3 className="dk-pg" aria-hidden="true">
                {section.group}
              </h3>
              {section.items.map((item, at) => {
                const index = section.start + at;
                const key = JSON.stringify(item.action);
                const hit = hits.get(key);
                const session =
                  "openChat" in item.action ? state.sessions[item.action.openChat] : undefined;
                const tone =
                  session === undefined
                    ? null
                    : chatStatus(session, pendingFor(state, session.id)).tone;
                return (
                  <button
                    key={key}
                    id={optionId(index)}
                    role="option"
                    aria-selected={index === p.selection}
                    className={index === p.selection ? "dk-pi on" : "dk-pi"}
                    onMouseMove={() => {
                      if (p.selection !== index) setP({ ...p, selection: index });
                    }}
                    onClick={() => {
                      run(item.action);
                    }}
                  >
                    <span className="dk-pglyph">
                      <ItemGlyph item={item} tone={tone} {...(hit === undefined ? {} : { hit })} />
                    </span>
                    {hit === undefined ? (
                      <>
                        <span className="dk-pt">{item.title}</span>
                        <span className="dk-ps">{item.subtitle}</span>
                      </>
                    ) : (
                      <span className="dk-phit">
                        <span className="dk-psnip">
                          <Snippet text={hit.snippet} />
                        </span>
                        <span className="dk-ps">{`${hit.title} · ${hit.repo}`}</span>
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}
