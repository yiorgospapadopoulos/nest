import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { Pixie, UpdatePixieBody } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ActivityPage } from "./ActivityPage.tsx";
import { Confirm } from "./Confirm.tsx";
import { FilePage } from "./FilePage.tsx";
import { HabitsPage } from "./HabitsPage.tsx";
import { InlineInput } from "./InlineInput.tsx";
import { factLines } from "./memory.ts";
import { MemoryPage } from "./MemoryPage.tsx";
import { PixieLimits } from "./PixieLimits.tsx";
import { PixieLook } from "./PixieLook.tsx";
import { PixieSettings } from "./PixieSettings.tsx";
import { PixieSkills } from "./PixieSkills.tsx";
import { Sprite } from "./Sprite.tsx";

/**
 * Everything that sets a pixie up, in one scrolling panel laid out like Monocode's Details
 * panel. Every change is saved at once; there is no form to submit (D072).
 */
export function PixieDetails({
  pixie,
  working,
  onOpenChat,
}: {
  pixie: Pixie;
  // At work, so its big sprite hops (B48); the page header shows it under Reduce Motion.
  working: boolean;
  // A chat named in its activity log.
  onOpenChat: (sessionId: string) => void;
}) {
  const { state, actions } = useStore();
  const { id } = pixie;
  const update = useCallback(
    (body: UpdatePixieBody) => actions.updatePixie(id, body),
    [actions, id],
  );
  const save = useCallback(
    (body: UpdatePixieBody) => {
      void update(body);
    },
    [update],
  );
  const [page, setPage] = useState<"soul" | "habits" | "memory" | "activity" | null>(null);
  const [confirm, setConfirm] = useState<"reset" | "delete" | null>(null);
  // Bumped when the memory page closes, to count the facts again.
  const [memoryRead, setMemoryRead] = useState(0);
  // The pixie saves facts during a turn, so a change to the pixie or its chat's state
  // (a turn ending) counts them again too.
  const chat = pixie.chat_session_id === null ? undefined : state.sessions[pixie.chat_session_id];
  const facts = useFactCount(id, `${String(memoryRead)} ${pixie.updated_at} ${chat?.state ?? ""}`);
  // Counted on the Habits row once the pixie's page loaded them, then kept live.
  const habits = state.habits[id];

  return (
    <>
      <PixieHeader pixie={pixie} working={working} save={save} />
      <PixieLook pixie={pixie} save={save} />

      <PixieSettings pixie={pixie} save={save} />

      <h2 className="pg-h">Chats it starts</h2>
      <PixieLimits pixie={pixie} save={update} />

      <PixieSkills pixie={pixie} save={update} />

      <div className="lgrp gl pxgap">
        <DrillIn
          title="Soul"
          about="Who this pixie is and the rules it follows"
          onOpen={() => {
            setPage("soul");
          }}
        />
        <DrillIn
          title="Habits"
          about="Recurring tasks this pixie runs on its own"
          onOpen={() => {
            setPage("habits");
          }}
        >
          {habits !== undefined &&
            `${String(habits.length)} ${habits.length === 1 ? "habit" : "habits"}`}
        </DrillIn>
        <DrillIn
          title="Memory"
          about="Facts and preferences this pixie remembers"
          onOpen={() => {
            setPage("memory");
          }}
        >
          {facts !== null && `${String(facts)} ${facts === 1 ? "fact" : "facts"}`}
        </DrillIn>
        <DrillIn
          title="Activity"
          about="What it did in your chats"
          onOpen={() => {
            setPage("activity");
          }}
        />
      </div>

      <div className="lgrp gl pxgap">
        <div className="srow">
          <span id="pixie-hidden">Hidden</span>
          <button
            className="sw"
            role="switch"
            aria-checked={pixie.hidden}
            aria-labelledby="pixie-hidden"
            onClick={() => {
              save({ hidden: !pixie.hidden });
            }}
          />
        </div>
      </div>
      <p className="hint gnote">A hidden pixie leaves the Pixies list. Its chat stays.</p>

      <div className="lgrp gl pxgap">
        <button
          className="pxrow-d pxdanger"
          aria-label="Reset conversation"
          aria-describedby="pixie-reset-about"
          onClick={() => {
            setConfirm("reset");
          }}
        >
          <span className="pxdt">
            <b>Reset conversation</b>
            <span id="pixie-reset-about">Clear all messages and start fresh</span>
          </span>
        </button>
        <button
          className="pxrow-d pxdanger"
          onClick={() => {
            setConfirm("delete");
          }}
        >
          <span className="pxdt">
            <b>Delete pixie</b>
          </span>
        </button>
      </div>

      {confirm === "reset" && (
        <Confirm
          title="Reset conversation?"
          about="The chat is archived. Soul and memory stay."
          action="Reset"
          onConfirm={() => void actions.resetPixie(id)}
          onClose={() => {
            setConfirm(null);
          }}
        />
      )}
      {confirm === "delete" && (
        <Confirm
          title={`Delete ${pixie.name}?`}
          about="Its chat, soul, memory and notes are removed."
          action="Delete"
          // Once it is gone, the page goes back by itself.
          onConfirm={() => void actions.deletePixie(id)}
          onClose={() => {
            setConfirm(null);
          }}
        />
      )}
      {page === "soul" && (
        <FilePage
          pixie={pixie}
          name="soul"
          title="Soul"
          onClose={() => {
            setPage(null);
          }}
        />
      )}
      {page === "habits" && (
        <HabitsPage
          pixie={pixie}
          onOpenChat={onOpenChat}
          onClose={() => {
            setPage(null);
          }}
        />
      )}
      {page === "activity" && (
        <ActivityPage
          pixie={pixie}
          onOpenChat={onOpenChat}
          onClose={() => {
            setPage(null);
          }}
        />
      )}
      {page === "memory" && (
        <MemoryPage
          pixie={pixie}
          onClose={() => {
            setPage(null);
            setMemoryRead((n) => n + 1);
          }}
        />
      )}
    </>
  );
}

/** The big sprite, then the name and the @slug, each edited in place. */
interface HeaderProps {
  pixie: Pixie;
  working: boolean;
  save: (body: UpdatePixieBody) => void;
}

function PixieHeader({ pixie, working, save }: HeaderProps) {
  const { actions } = useStore();
  const [editing, setEditing] = useState<"name" | "slug" | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const stop = () => {
    setEditing(null);
  };
  return (
    <div className="pxhead">
      <Sprite
        mascot={pixie.mascot}
        color={pixie.color}
        size={80}
        working={working}
        phaseKey={pixie.id}
      />
      {editing === "name" ? (
        <InlineInput
          label="Name"
          initial={pixie.name}
          className="pxin pxname"
          onDone={(name) => {
            stop();
            if (name && name !== pixie.name) save({ name });
          }}
        />
      ) : (
        <button
          className="pxedit pxname"
          aria-label={`Edit name, ${pixie.name}`}
          onClick={() => {
            setEditing("name");
          }}
        >
          {pixie.name}
        </button>
      )}
      {editing === "slug" ? (
        <InlineInput
          label="Slug"
          initial={pixie.slug}
          className="pxin pxslug"
          onDone={(slug) => {
            stop();
            if (slug && slug !== pixie.slug) {
              void actions.setPixieSlug(pixie.id, slug).then(setRefused);
            }
          }}
        />
      ) : (
        <button
          className="pxedit pxslug"
          aria-label={`Edit slug, @${pixie.slug}`}
          onClick={() => {
            setEditing("slug");
          }}
        >
          @{pixie.slug}
        </button>
      )}
      {refused !== null && (
        <p className="pxerr" role="alert">
          {refused}
        </p>
      )}
    </div>
  );
}

/**
 * The facts in MEMORY.md, counted again for each new `version`. A count that cannot be
 * read keeps the last one, without a toast.
 */
function useFactCount(id: string, version: string): number | null {
  const { actions } = useStore();
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    void actions.peekPixieFile(id, "memory").then((file) => {
      if (file !== null) setCount(factLines(file.text).length);
    });
  }, [actions, id, version]);
  return count;
}

interface DrillInProps {
  title: string;
  about: string;
  onOpen: () => void;
  children?: ReactNode;
}

/** A row that opens a page: title, a line about it, a count or note, and a chevron. */
function DrillIn({ title, about, onOpen, children }: DrillInProps) {
  const body = (
    <>
      <span className="pxdt">
        <b>{title}</b>
        <span>{about}</span>
      </span>
      <span className="pxn">{children}</span>
    </>
  );
  return (
    <button className="pxrow-d" onClick={onOpen}>
      {body}
      <Icon name="chevr" className="chv" />
    </button>
  );
}
