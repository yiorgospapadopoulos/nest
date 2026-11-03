import { useEffect, useRef, useState } from "react";
import type { Pixie, UpdatePixieBody } from "../../api/types.ts";
import { MASCOT_SPRITES, PIXIE_COLORS } from "../../generated/mascots.ts";
import { KIND_LABELS } from "../../screens/artifacts/view.ts";
import { MASCOTS } from "../../screens/pixies/options.ts";
import { artifactList } from "../../store/artifacts.ts";
import { CLAUDE } from "../../store/catalog.ts";
import { useStore } from "../../store/context.ts";
import { pixieWorking, supportsFeature } from "../../store/selectors.ts";
import { when } from "../artifacts/text.ts";
import { useOpenArtifact } from "../artifacts/viewState.ts";
import { Confirm } from "../sheets/Alert.tsx";
import { useShell } from "../shell/context.ts";
import { Toggle } from "../ui/controls.tsx";
import type { MenuEntry } from "../ui/menuItems.ts";
import { RenameField } from "../ui/RenameField.tsx";
import { useNow } from "./useNow.ts";
import type { PixiePage } from "./panel.ts";
import {
  DangerRow,
  DetailHeading,
  DetailLine,
  DetailNote,
  DrillInRow,
  HeadingAddMenu,
  PickerRow,
  RemoveButton,
  SectionBreak,
  StepperRow,
} from "./parts.tsx";
import { settingsRows } from "./settingsMenus.ts";
import { Sprite, WorkingDot } from "./Sprite.tsx";
import { factCount, LIMITS, shortName, skillMenu } from "./words.ts";

// The artifacts listed on the page; the Artifacts view holds the rest (B79).
const ARTIFACTS_SHOWN = 5;

interface Props {
  pixie: Pixie;
  open: (page: PixiePage) => void;
}

/**
 * Everything that sets a pixie up, in one scrolling panel (PixieDetails.swift). Every
 * change is saved at once; there is no form to submit (D072).
 */
export function PixieDetails({ pixie, open }: Props) {
  const { state, actions } = useStore();
  const [confirming, setConfirming] = useState<"reset" | "delete" | null>(null);
  // "3 facts", once MEMORY.md is read.
  const [facts, setFacts] = useState<{ key: string; text: string } | null>(null);
  const save = (body: UpdatePixieBody) => void actions.updatePixie(pixie.id, body);
  const chat = pixie.chat_session_id === null ? undefined : state.sessions[pixie.chat_session_id];
  const inFlight = chat?.state === "starting" || chat?.state === "running";
  const habits = state.habits[pixie.id];

  // Read quietly, again when the pixie changes or its chat ends a turn: it may have
  // remembered something.
  const factsKey = `${pixie.id} ${pixie.updated_at} ${String(inFlight)}`;
  useEffect(() => {
    let current = true;
    void actions.peekPixieFile(pixie.id, "memory").then((file) => {
      if (current && file !== null) setFacts({ key: pixie.id, text: factCount(file.text) });
    });
    return () => {
      current = false;
    };
  }, [actions, pixie.id, factsKey]);
  const unknownModels = state.modelLists[CLAUDE] === undefined;
  useEffect(() => {
    if (unknownModels) void actions.loadChoices();
  }, [actions, unknownModels]);
  const known = habits !== undefined;
  useEffect(() => {
    if (!known) void actions.loadHabits(pixie.id);
  }, [actions, pixie.id, known]);

  return (
    <div className="pd-scroll pd-details">
      <Identity pixie={pixie} />
      <Look pixie={pixie} save={save} />
      <SectionBreak />
      {settingsRows(state, pixie, save).map((row) => (
        <PickerRow
          key={row.title}
          title={row.title}
          value={row.value}
          enabled={row.enabled}
          items={row.items}
        />
      ))}

      <DetailHeading title="Limits" />
      <StepperRow
        title={LIMITS.running.title}
        value={pixie.max_running}
        min={LIMITS.running.min}
        max={LIMITS.running.max}
        onChange={(value) => {
          save({ max_running: value });
        }}
      />
      <StepperRow
        title={LIMITS.perDay.title}
        value={pixie.max_per_day}
        min={LIMITS.perDay.min}
        max={LIMITS.perDay.max}
        onChange={(value) => {
          save({ max_per_day: value });
        }}
      />

      {/* Only an engine that takes a pixie's own skill list shows it (B91). */}
      {supportsFeature(state, "pixie_skills", pixie.provider) && (
        <Skills pixie={pixie} save={save} />
      )}

      <SectionBreak />
      <DrillInRow
        title="Soul"
        about="Who this pixie is and the rules it follows"
        onOpen={() => {
          open({ page: "soul" });
        }}
      />
      <DrillInRow
        title="Habits"
        about="Recurring tasks this pixie runs on its own"
        value={
          habits === undefined
            ? null
            : habits.length === 1
              ? "1 habit"
              : `${String(habits.length)} habits`
        }
        onOpen={() => {
          open({ page: "habits" });
        }}
      />
      <DrillInRow
        title="Memory"
        about="Facts and preferences this pixie remembers"
        value={facts?.key === pixie.id ? facts.text : null}
        onOpen={() => {
          open({ page: "memory" });
        }}
      />
      <DrillInRow
        title="Activity"
        about="What it did in your chats with its tools"
        onOpen={() => {
          open({ page: "activity" });
        }}
      />

      <DetailHeading title="Artifacts" />
      <Artifacts pixie={pixie} />

      <SectionBreak />
      <div className="pd-toggle">
        <span>Hidden</span>
        <Toggle
          label="Hidden"
          checked={pixie.hidden}
          onChange={(hidden) => {
            save({ hidden });
          }}
        />
      </div>
      <DetailNote text="A hidden pixie leaves the Pixies list. Its chat stays." />

      <SectionBreak />
      <DangerRow
        title="Reset conversation"
        about="Clear all messages and start fresh"
        onClick={() => {
          setConfirming("reset");
        }}
      />
      <DangerRow
        title="Delete pixie"
        onClick={() => {
          setConfirming("delete");
        }}
      />
      {confirming !== null && (
        <Confirm
          destructive
          title={confirming === "delete" ? `Delete ${pixie.name}?` : "Reset conversation?"}
          message={
            confirming === "delete"
              ? "Its chat, soul, memory and notes are removed."
              : "The chat is archived. Soul and memory stay."
          }
          action={confirming === "delete" ? "Delete" : "Reset"}
          onConfirm={() => {
            setConfirming(null);
            if (confirming === "delete") void actions.deletePixie(pixie.id);
            else void actions.resetPixie(pixie.id);
          }}
          onClose={() => {
            setConfirming(null);
          }}
        />
      )}
    </div>
  );
}

/** The big sprite, then the name and the @slug, each edited in place. */
function Identity({ pixie }: { pixie: Pixie }) {
  const { state, actions } = useStore();
  const [editing, setEditing] = useState<"name" | "slug" | null>(null);
  // Why the last slug was refused.
  const [refused, setRefused] = useState<string | null>(null);
  const working = pixieWorking(state, pixie);
  const done = () => {
    setEditing(null);
  };
  return (
    <div className="pd-identity">
      <span className="pd-big">
        <Sprite
          mascot={pixie.mascot}
          color={pixie.color}
          size={63}
          working={working}
          phaseKey={pixie.id}
        />
        <span className="pd-bigdot">
          <WorkingDot working={working} />
        </span>
      </span>
      {editing === "name" ? (
        <RenameField
          value={pixie.name}
          label="Name"
          className="pd-inline name"
          onCommit={(name) => {
            done();
            void actions.updatePixie(pixie.id, { name });
          }}
          onCancel={done}
        />
      ) : (
        <button
          className="pd-editable name"
          title="Edit name"
          aria-label={`Edit name, ${pixie.name}`}
          onClick={() => {
            setEditing("name");
          }}
        >
          {pixie.name}
        </button>
      )}
      {editing === "slug" ? (
        <RenameField
          value={pixie.slug}
          label="Slug"
          className="pd-inline"
          onCommit={(slug) => {
            done();
            void actions.setPixieSlug(pixie.id, slug).then(setRefused);
          }}
          onCancel={done}
        />
      ) : (
        <button
          className="pd-editable slug"
          title="Edit slug"
          aria-label={`Edit slug, @${pixie.slug}`}
          onClick={() => {
            setRefused(null);
            setEditing("slug");
          }}
        >
          @{pixie.slug}
        </button>
      )}
      {refused !== null && <p className="pd-refused">{refused}</p>}
    </div>
  );
}

const capitalized = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);

/** Mascots and colours; a click saves the choice. */
function Look({ pixie, save }: { pixie: Pixie; save: (body: UpdatePixieBody) => void }) {
  const custom = !PIXIE_COLORS.includes(pixie.color.toUpperCase());
  return (
    <div className="pd-look">
      <div className="pd-mascots" role="radiogroup" aria-label="Mascot">
        {MASCOTS.filter((m) => m in MASCOT_SPRITES).map((mascot) => (
          <button
            key={mascot}
            role="radio"
            aria-checked={pixie.mascot === mascot}
            aria-label={`Mascot ${mascot}`}
            title={capitalized(mascot)}
            className={pixie.mascot === mascot ? "on" : undefined}
            onClick={() => {
              save({ mascot });
            }}
          >
            <Sprite mascot={mascot} color={pixie.color} size={20} />
          </button>
        ))}
      </div>
      <div className="pd-colors" role="radiogroup" aria-label="Colour">
        {PIXIE_COLORS.map((color) => (
          <button
            key={color}
            role="radio"
            aria-checked={pixie.color.toUpperCase() === color}
            aria-label={`Colour ${color}`}
            title={color}
            className={pixie.color.toUpperCase() === color ? "pd-color on" : "pd-color"}
            onClick={() => {
              save({ color });
            }}
          >
            <span style={{ background: color }} />
          </button>
        ))}
        <CustomColor
          color={pixie.color}
          on={custom}
          pick={(color) => {
            save({ color });
          }}
        />
      </div>
    </div>
  );
}

/**
 * The rainbow dot: a click opens the colour picker. The colour is saved once the user
 * stops moving it, not on every step.
 */
function CustomColor({
  color,
  on,
  pick,
}: {
  color: string;
  on: boolean;
  pick: (color: string) => void;
}) {
  const timer = useRef<number | undefined>(undefined);
  useEffect(
    () => () => {
      window.clearTimeout(timer.current);
    },
    [],
  );
  return (
    <label
      className={on ? "pd-color pd-custom on" : "pd-color pd-custom"}
      title={on ? `Custom colour ${color}` : "Custom colour"}
    >
      <span />
      <input
        type="color"
        aria-label="Custom colour"
        value={color.toLowerCase()}
        onChange={(event) => {
          const hex = event.target.value.toUpperCase();
          window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => {
            if (hex !== color.toUpperCase()) pick(hex);
          }, 600);
        }}
      />
    </label>
  );
}

/**
 * The skills it may use, as removable chips; Add, at the right of the heading, offers the
 * skills not chosen yet (B85): standalone ones, then a submenu per plugin. None chosen
 * means every skill.
 */
function Skills({ pixie, save }: { pixie: Pixie; save: (body: UpdatePixieBody) => void }) {
  const { actions } = useStore();
  const [choices, setChoices] = useState<Awaited<ReturnType<typeof actions.pixieSkills>>>(null);
  useEffect(() => {
    let current = true;
    void actions.pixieSkills().then((loaded) => {
      if (current) setChoices(loaded);
    });
    return () => {
      current = false;
    };
  }, [actions]);
  const items = (): MenuEntry[] => {
    const menu = skillMenu(choices ?? [], pixie.skills);
    const add = (name: string) => () => {
      save({ skills: [...pixie.skills, name] });
    };
    return [
      ...(menu.empty === null ? [] : [{ type: "note" as const, text: menu.empty }]),
      ...menu.standalone.map((skill) => ({
        title: shortName(skill),
        onSelect: add(skill.name),
      })),
      ...(menu.standalone.length > 0 && menu.groups.length > 0
        ? [{ type: "separator" as const }]
        : []),
      ...menu.groups.map((group) => ({
        type: "submenu" as const,
        title: group.plugin,
        items: group.skills.map((skill) => ({
          title: shortName(skill),
          onSelect: add(skill.name),
        })),
      })),
    ];
  };
  return (
    <>
      <DetailHeading title="Skills">
        <HeadingAddMenu label="Add skill" items={items} />
      </DetailHeading>
      <div className="pd-chips">
        {pixie.skills.length === 0 && <span className="pd-allskills">All skills</span>}
        {pixie.skills.map((skill) => (
          <span key={skill} className="pd-chip">
            <span>{skill}</span>
            <RemoveButton
              label={`Remove ${skill}`}
              onClick={() => {
                save({ skills: pixie.skills.filter((each) => each !== skill) });
              }}
            />
          </span>
        ))}
      </div>
    </>
  );
}

/** The pixie's artifacts, newest first (B79), each opening in the Artifacts view. */
function Artifacts({ pixie }: { pixie: Pixie }) {
  const { state, actions } = useStore();
  const shell = useShell();
  const openArtifact = useOpenArtifact();
  const now = useNow(30_000);
  useEffect(() => {
    void actions.loadArtifacts({ pixie_id: pixie.id });
  }, [actions, pixie.id]);
  const artifacts = artifactList(state, { pixie_id: pixie.id });
  if (artifacts === null) return null;
  return (
    <>
      {artifacts.length === 0 && <DetailLine text="None yet" dim />}
      {artifacts.slice(0, ARTIFACTS_SHOWN).map((artifact) => (
        <DrillInRow
          key={artifact.id}
          title={artifact.title}
          about={`${KIND_LABELS[artifact.kind]} · ${when(artifact.updated_at, now)}`}
          value={artifact.seen ? null : "New"}
          onOpen={() => {
            openArtifact(artifact.id, artifact.latest_version);
          }}
        />
      ))}
      {artifacts.length > ARTIFACTS_SHOWN && (
        <DrillInRow
          title="All artifacts"
          about={`${String(artifacts.length)} saved`}
          onOpen={() => {
            shell.setView("artifacts");
          }}
        />
      )}
    </>
  );
}
