import { useState } from "react";
import type { Mascot } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { pixieList } from "../../store/selectors.ts";
import { Icon } from "../../ui/Icon.tsx";
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

/** The user's pixies above the projects, each opening its page, and New pixie. */
export function PixieSection({ onOpen }: Props) {
  const { state, actions } = useStore();
  const [showHidden, setShowHidden] = useState(false);
  const pixies = pixieList(state, showHidden);
  const hidden = pixieList(state, true).length - pixieList(state).length;

  const create = async (body: Parameters<typeof actions.createPixie>[0], tab: PixieTab) => {
    const created = await actions.createPixie(body);
    if (created !== null) onOpen(created.id, tab);
  };

  return (
    <section className="pxsec" aria-labelledby="pixies-title">
      <h2 className="pg-h" id="pixies-title">
        Pixies
        <span className="gc">{pixies.length}</span>
      </h2>
      <div className="lgrp gl">
        {pixies.map((p) => {
          const chat = p.chat_session_id === null ? undefined : state.sessions[p.chat_session_id];
          const running = chat?.state === "running";
          return (
            <div key={p.id} className="lrow">
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
        })}
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
