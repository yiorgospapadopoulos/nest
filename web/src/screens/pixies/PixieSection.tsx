import { useState } from "react";
import type { Mascot, Pixie } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { pixieList } from "../../store/selectors.ts";
import { Icon } from "../../ui/Icon.tsx";
import { usePending } from "./pending.ts";
import type { PixieTab } from "./PixieView.tsx";
import { Sprite } from "./Sprite.tsx";

// One-tap starters while the user has no pixies; nothing is created without the tap (D072).
const TEMPLATES: readonly { name: string; mascot: Mascot; soul: string }[] = [
  {
    name: "Reviewer",
    mascot: "owl",
    soul:
      "You review code changes. Look for bugs, missing tests and unclear names first, " +
      "style last. Say what you checked, then list problems by severity with file and line.",
  },
  {
    name: "Tester",
    mascot: "robot",
    soul:
      "You test changes. Find how the project runs its tests, run them, add missing " +
      "cases for the change, and report what passed, what failed and why.",
  },
];

// The colour a new pixie gets.
const DEFAULT_COLOR = "#8B7CF6";

interface Props {
  onOpen: (id: string, tab: PixieTab) => void;
}

/**
 * The user's pixies above the projects, each opening its page, and New pixie. Edit order
 * turns the rows into up and down buttons: a long-press drag fights the page's scrolling
 * and Safari's text selection on a touch screen, and buttons work with VoiceOver too.
 */
export function PixieSection({ onOpen }: Props) {
  const { state, actions } = useStore();
  const [showHidden, setShowHidden] = useState(false);
  const [ordering, setOrdering] = useState(false);
  // Every pixie's id, hidden ones too: the order the Mac saves names them all.
  const [order, setOrder] = usePending(
    pixieList(state, true).map((p) => p.id),
    (ids) => actions.reorderPixies(ids),
  );
  const pixies = order.flatMap((id) => {
    const p = state.pixies[id];
    return p === undefined || (p.hidden && !showHidden) ? [] : [p];
  });
  const hidden = pixieList(state, true).length - pixieList(state).length;

  const create = async (body: Parameters<typeof actions.createPixie>[0], tab: PixieTab) => {
    const created = await actions.createPixie(body);
    if (created !== null) onOpen(created.id, tab);
  };

  /** Moves pixie `id` next to `other`, before it or after it, among all of them. */
  const place = (id: string, other: string, after: boolean) => {
    const rest = order.filter((each) => each !== id);
    const at = rest.indexOf(other) + (after ? 1 : 0);
    setOrder([...rest.slice(0, at), id, ...rest.slice(at)]);
  };

  return (
    <section className="pxsec" aria-labelledby="pixies-title">
      <h2 className="pg-h" id="pixies-title">
        Pixies
        <span className="gc">{pixies.length}</span>
        {(ordering || pixies.length > 1) && (
          <button
            className="lnk pxordb"
            onClick={() => {
              setOrdering(!ordering);
            }}
          >
            {ordering ? "Done" : "Edit order"}
          </button>
        )}
      </h2>
      <div className="lgrp gl">
        {pixies.map((p, index) =>
          ordering ? (
            <OrderRow
              key={p.id}
              pixie={p}
              before={pixies[index - 1]}
              after={pixies[index + 1]}
              place={place}
            />
          ) : (
            <PixieRow
              key={p.id}
              pixie={p}
              running={
                p.chat_session_id !== null && state.sessions[p.chat_session_id]?.state === "running"
              }
              onOpen={onOpen}
            />
          ),
        )}
        {!ordering && (
          <div className="lrow">
            <button
              className="row pxr pxnew"
              onClick={() => void create({ name: "New pixie" }, "details")}
            >
              <span className="pxplus" aria-hidden="true">
                <Icon name="plus" />
              </span>
              <span className="rt">New pixie</span>
            </button>
          </div>
        )}
        {hidden > 0 && (
          <div className="lrow">
            <button
              className="row pxr pxhid"
              onClick={() => {
                setShowHidden(!showHidden);
              }}
            >
              <span className="rt">
                {showHidden ? "Hide hidden" : `Show hidden (${String(hidden)})`}
              </span>
            </button>
          </div>
        )}
      </div>
      {Object.keys(state.pixies).length === 0 && (
        <div className="pxtpl">
          <span className="hint">Or start from a template</span>
          {TEMPLATES.map((t) => (
            <button
              key={t.name}
              className="pxtb gl"
              onClick={() => void create({ name: t.name, mascot: t.mascot, soul: t.soul }, "chat")}
            >
              <span aria-hidden="true">
                <Sprite mascot={t.mascot} color={DEFAULT_COLOR} size={20} />
              </span>
              <span>{t.name}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

interface RowProps {
  pixie: Pixie;
  running: boolean;
  onOpen: (id: string, tab: PixieTab) => void;
}

function PixieRow({ pixie: p, running, onOpen }: RowProps) {
  return (
    <div className="lrow">
      <button
        className="row pxr"
        aria-label={`${p.name}, @${p.slug}${running ? ", running" : ""}`}
        data-chat={`pixie:${p.id}`}
        onClick={() => {
          onOpen(p.id, "chat");
        }}
      >
        <Sprite mascot={p.mascot} color={p.color} size={28} />
        <span className="rt">{p.name}</span>
        <span className="rm">
          {running && <span className="prun" />}@{p.slug}
        </span>
        <Icon name="chevr" className="chv" />
      </button>
    </div>
  );
}

interface OrderRowProps {
  pixie: Pixie;
  // The pixies shown above and below it, if any.
  before: Pixie | undefined;
  after: Pixie | undefined;
  place: (id: string, other: string, after: boolean) => void;
}

/** A pixie while ordering: its name and buttons that move it past the next one shown. */
function OrderRow({ pixie: p, before, after, place }: OrderRowProps) {
  return (
    <div className="lrow">
      <div className="row pxr">
        <Sprite mascot={p.mascot} color={p.color} size={28} />
        <span className="rt">{p.name}</span>
        <button
          className="pxmv"
          aria-label={`Move ${p.name} up`}
          disabled={before === undefined}
          onClick={
            before &&
            (() => {
              place(p.id, before.id, false);
            })
          }
        >
          <Icon name="chev" className="up" />
        </button>
        <button
          className="pxmv"
          aria-label={`Move ${p.name} down`}
          disabled={after === undefined}
          onClick={
            after &&
            (() => {
              place(p.id, after.id, true);
            })
          }
        >
          <Icon name="chev" />
        </button>
      </div>
    </div>
  );
}
