import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { Sprite, TeamFace, WorkingDot } from "./pixies/Sprite.tsx";
import type { Pixie } from "../api/types.ts";
import { useReducedMotion } from "../screens/pixies/motion.ts";
import { useStore } from "../store/context.ts";
import { deviceStorage } from "../store/legacyKeys.ts";
import type { OpenTarget } from "./bridge.ts";
import { useBridge } from "./context.ts";
import {
  isAlert,
  islandAction,
  islandState,
  listRows,
  placeSession,
  seenChat,
  STATUS_WORDS,
  type IslandAction,
  type IslandEntry,
  type IslandPlace,
  type IslandTarget,
  type Nightshade,
} from "./island.ts";
import {
  installedAt,
  ISLAND_SETTINGS_KEY,
  loadIslandSettings,
  loadSeen,
  markSeen,
  SEEN_KEY,
  snapshotOf,
} from "./islandData.ts";
import { pillHover, type PillHover, type Zone } from "./pillHover.ts";
import { listAlpha } from "./pillMotion.ts";
import {
  createScene,
  FLIGHT_ROOM,
  leaving,
  plusX,
  SPRITE,
  STRIP_HEIGHT as STRIP,
  type DrawnSprite,
  type Landing,
  type SceneFrame,
  type SceneInput,
  type SceneItem,
} from "./pillScene.ts";
import { pillSizer, pillStripWidth, type PillSize, type PillSizer } from "./pillSize.ts";

// The Mac's pill (IslandScene.swift): each row of the open list, the list's room above and
// below its rows, and the open list's width.
const ROW = 46;
const LIST_TOP = 6;
const LIST_BOTTOM = 12;
const LIST_WIDTH = 420;
const NIGHTSHADE = "#8B7CF6";
const BLUEBELL = "#0090FF";
// A frame comes this soon at the latest: the Mac's 20 a second for hops.
const FRAME_FALLBACK_MS = 50;

/** Where an action takes the main window. */
function targetOf(place: IslandPlace, approval?: string): OpenTarget {
  if ("pixieChat" in place) return { pixie: place.pixie };
  if ("habitRun" in place) return { habitRun: place.habitRun };
  return approval === undefined ? { chat: place.chat } : { chat: place.chat, approval };
}

/** What a sprite on the strip shows: Nightshade, the resting Bluebell, or an entry. */
type Fig =
  | { kind: "nightshade"; mode: Nightshade }
  | { kind: "bluebell"; asleep: boolean }
  | { kind: "entry"; entry: IslandEntry };

function landingOf(entry: IslandEntry): Landing {
  if (entry.status === "done") return "done";
  return isAlert(entry.status) ? "alert" : "none";
}

/** A pixie's colour, a team's first known member's (its sparks and trail). */
function colorOf(entry: IslandEntry, pixies: Record<string, Pixie>): string {
  const { figure } = entry;
  if ("pixie" in figure) return figure.pixie.color;
  const first = figure.members.map((m) => pixies[m.pixie_id]).find((p) => p !== undefined);
  return first?.color ?? NIGHTSHADE;
}

/**
 * The pixie pill's own window (desktop.html?view=pill), always shown while Nest runs, as the
 * Mac's island in the menu bar (B114): working pixies hop on the left, or Nightshade sits
 * there (and hops while a normal chat works, and sleeps when all is quiet); pixies that
 * finished or need the user wait on the right until their chat is seen. Hovering opens the
 * list, with Nightshade's "Nothing running" row when it is empty; a click opens Nest where
 * it is needed (IslandAction). What moves follows the Mac's IslandScene (pillScene.ts).
 */
export function Pill() {
  const { state, actions } = useStore();
  const bridge = useBridge();
  const storage = deviceStorage();
  const reduce = useReducedMotion();
  const [open, setOpen] = useState(false);
  const hover = useRef<PillHover | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [awakeSince] = useState(() => Date.now());
  const [installed] = useState(() => installedAt(storage, Date.now()));
  const [seen, setSeen] = useState(() => loadSeen(storage));
  const [settings, setSettings] = useState(() => loadIslandSettings(storage));

  // The main window marks chats seen; the pill hears it through the shared storage.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === SEEN_KEY) setSeen(loadSeen(storage));
      if (event.key === ISLAND_SETTINGS_KEY) setSettings(loadIslandSettings(storage));
    };
    window.addEventListener("storage", onStorage);
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 15_000);
    document.documentElement.classList.add("pill-page");
    return () => {
      window.removeEventListener("storage", onStorage);
      window.clearInterval(timer);
    };
  }, [storage]);

  // Habit runs come from each pixie's habits, then from the live events.
  const pixieIds = Object.keys(state.pixies).sort().join(" ");
  useEffect(() => {
    for (const id of pixieIds.split(" ").filter(Boolean)) void actions.loadHabits(id);
  }, [actions, pixieIds]);

  const island = useMemo(
    () =>
      islandState(snapshotOf(state, { seen, installedAt: installed, awakeSince, settings }, now)),
    [state, seen, installed, awakeSince, settings, now],
  );
  const rows = listRows(island);
  const strip = pillStripWidth(
    island.nightshade !== null ? 1 : island.left.length,
    island.restingBluebell ? 1 : island.right.length,
  );
  const listHeight = LIST_TOP + rows * ROW + LIST_BOTTOM;
  const width = open ? Math.max(strip.width, LIST_WIDTH) : strip.width;
  const height = open ? STRIP + listHeight : STRIP;

  // What each sprite shows travels with it through the scene, also while it leaves.
  const sceneInput: SceneInput<Fig> = useMemo(() => {
    const item = (id: string, color: string, landing: Landing, fig: Fig): SceneItem<Fig> => ({
      id,
      color,
      landing,
      data: fig,
    });
    const entries = (list: IslandEntry[]) =>
      list.map((entry) =>
        item(entry.id, colorOf(entry, state.pixies), landingOf(entry), { kind: "entry", entry }),
      );
    return {
      left:
        island.nightshade !== null
          ? [
              item("nightshade", NIGHTSHADE, "none", {
                kind: "nightshade",
                mode: island.nightshade,
              }),
            ]
          : entries(island.left),
      right: island.restingBluebell
        ? [
            item("bluebell", BLUEBELL, "none", {
              kind: "bluebell",
              asleep: island.nightshade === "asleep",
            }),
          ]
        : entries(island.right),
      sideWidth: strip.side,
      wantsOpen: false,
      reduce,
    };
  }, [island, state.pixies, strip.side, reduce]);

  // A finished pixie whose chat was just seen pops as it leaves; any other fades.
  const [scene] = useState(() => createScene<Fig>());
  const before = useRef<IslandEntry[]>([]);
  useEffect(() => {
    const ids = new Set(island.list.map((e) => e.id));
    for (const entry of before.current) {
      if (ids.has(entry.id)) continue;
      if (leaving(entry.status, entry.since, seen[placeSession(entry.place)]) === "pop") {
        scene.pop(entry.id);
      }
    }
    before.current = island.list;
  }, [island, seen, scene]);

  // The window grows before the list opens in it (pillSize.ts); the scene eases toward
  // whatever the window has room for.
  const [roomy, setRoomy] = useState<PillSize>(() => ({ width: strip.width, height: STRIP }));
  const sizer = useRef<PillSizer | null>(null);
  useEffect(() => {
    const next = pillSizer(
      (size) => bridge.pillUpdate(size),
      (size) => {
        setRoomy(size);
      },
    );
    sizer.current = next;
    return () => {
      next.dispose();
      sizer.current = null;
    };
  }, [bridge]);

  // The scene's frames, stepped while anything moves: on the next animation frame, or on a
  // timer when none comes, as WebKit holds them back for a window it does not count as
  // shown (B117 VM re-check: two pixies worked and the pill stayed still).
  const [frame, setFrame] = useState<SceneFrame<Fig> | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const input = useRef(sceneInput);
  const kick = useRef<() => void>(() => undefined);
  useEffect(() => {
    let raf: number | null = null;
    let timer: number | null = null;
    const stop = () => {
      if (raf !== null) window.cancelAnimationFrame(raf);
      if (timer !== null) window.clearTimeout(timer);
      raf = null;
      timer = null;
    };
    const tick = () => {
      stop();
      const next = scene.step(performance.now(), input.current);
      setFrame(next);
      drawParticles(canvas.current, next);
      if (next.moving) schedule();
    };
    const schedule = () => {
      if (raf !== null || timer !== null) return;
      raf = window.requestAnimationFrame(tick);
      timer = window.setTimeout(tick, FRAME_FALLBACK_MS);
    };
    kick.current = schedule;
    schedule();
    return () => {
      stop();
      kick.current = () => undefined;
    };
  }, [scene]);
  useEffect(() => {
    input.current = { ...sceneInput, wantsOpen: roomy.height > STRIP };
    kick.current();
  }, [sceneInput, roomy]);

  // What takes clicks now: the pill's size, which the window's shape follows at once; and
  // room below the strip while a pixie flies there.
  const under = frame?.under === true;
  const shape = useRef<PillSize>({ width, height });
  useEffect(() => {
    shape.current = { width, height };
    sizer.current?.want({ width, height }, under ? FLIGHT_ROOM : 0);
  }, [width, height, under]);
  useEffect(() => {
    void bridge.pillUpdate({ visible: settings.shown });
  }, [bridge, settings.shown]);

  // The pointer over the strip or the open list, followed through the whole page: the
  // window's edges and its shape changing under a still pointer give no enter or leave on
  // the pill's own elements.
  useEffect(() => {
    // Where a point of the window is (CSS px): on the strip, on the pill's shape (what
    // takes clicks, centred at the top, already the open pill's while it eases open, so a
    // pointer that stopped where the list still grows keeps it open), or neither.
    const zoneAt = (x: number, y: number): Zone | null => {
      const bar = document.querySelector(".dk-pstrip")?.getBoundingClientRect();
      if (bar === undefined) return null;
      const inside = (left: number, top: number, right: number, bottom: number) =>
        x >= left && x < right && y >= top && y < bottom;
      if (inside(bar.left, bar.top, bar.right, bar.bottom)) return "strip";
      const { width: w, height: h } = shape.current;
      const left = (window.innerWidth - w) / 2;
      return inside(left, 0, left + w, h) ? "list" : "out";
    };
    // The same, where the window system finds the pointer.
    const probe = async (): Promise<Zone | null> => {
      const at = await bridge.pillPointer();
      return at === null ? null : zoneAt(at.x, at.y);
    };
    const next = pillHover(setOpen, probe);
    hover.current = next;
    const onMove = (event: PointerEvent) => {
      next.move(
        { x: event.screenX, y: event.screenY },
        zoneAt(event.clientX, event.clientY) ?? "out",
      );
    };
    // Leaving the window: out of the page, to no element.
    const onOut = (event: globalThis.MouseEvent) => {
      if (event.relatedTarget === null) next.leave();
    };
    // A pointer that comes in without moving (a jump, a window shrinking to it) is over.
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerover", onMove);
    window.addEventListener("mouseout", onOut);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerover", onMove);
      window.removeEventListener("mouseout", onOut);
      next.dispose();
      hover.current = null;
    };
  }, [bridge]);

  const click = (target: IslandTarget) => {
    const action: IslandAction = islandAction(target);
    if ("showList" in action) {
      hover.current?.pin();
      return;
    }
    const chat = seenChat(action);
    if (chat !== null) {
      markSeen(storage, chat, Date.now());
      setSeen(loadSeen(storage));
    }
    hover.current?.dismiss();
    let goTo: OpenTarget = { home: true };
    if ("open" in action) goTo = targetOf(action.open);
    else if ("openApproval" in action) goTo = targetOf(action.openApproval, action.approval);
    void bridge.openInMain(goTo);
  };
  const openNest = () => {
    click({ strip: true });
  };
  // As the Mac's IslandView.mouseUp: the figure under the pointer, else the strip.
  const onStrip = (event: MouseEvent<HTMLDivElement>) => {
    if ((event.target as Element).closest("button") === null) openNest();
  };

  if (!settings.shown) return null;

  // The strip and the shape, as IslandScene draws them this frame.
  const sideLeft = frame?.leftWidth ?? strip.side;
  const sideRight = frame?.rightWidth ?? strip.side;
  const stripWidth = sideLeft + sideRight + 24;
  const openness = frame?.open ?? 0;
  const eased = frame?.eased ?? 0;
  const shapeWidth = stripWidth + (Math.max(stripWidth, LIST_WIDTH) - stripWidth) * eased;
  const shapeHeight = STRIP + listHeight * eased;
  const sprites = frame?.sprites ?? [];
  const resting = sprites.filter((s) => !s.flying);
  const flying = sprites.filter((s) => s.flying);
  const half = stripWidth / 2;
  const counts = (["left", "right"] as const).flatMap((side) => {
    const list = side === "left" ? island.left : island.right;
    const atRest = side === "left" ? island.nightshade !== null : island.restingBluebell;
    const more = atRest ? [] : list.slice(3);
    if (more.length === 0) return [];
    const x = plusX(side, side === "left" ? sideLeft : sideRight, 3);
    return [{ side, x, more }];
  });

  return (
    <>
      <div
        className={open ? "dk-pill open" : "dk-pill"}
        style={{
          width: shapeWidth,
          height: shapeHeight,
          borderRadius: 17 + 3 * eased,
        }}
      >
        {/* The whole top row takes the strip's clicks, also where the open pill is wider
            than the strip, as the Mac's IslandView.mouseUp. */}
        <div onClick={onStrip}>
          <div className="dk-pstrip" style={{ width: stripWidth }}>
            <span className="dk-pdot" aria-hidden="true" />
            {resting.map((drawn) => (
              <StripSprite
                key={drawn.id}
                drawn={drawn}
                fig={drawn.data}
                left={drawn.x + half}
                onClick={click}
              />
            ))}
            {counts.map(({ side, x, more }) => (
              <button
                key={side}
                className={more.some((e) => isAlert(e.status)) ? "dk-pmore alert" : "dk-pmore"}
                style={{ left: x - 3 + half }}
                aria-label={`${String(more.length)} more`}
                onClick={() => {
                  click({ more: true });
                }}
              >
                +{more.length}
              </button>
            ))}
          </div>
        </div>
        {/* Always there under the strip, so it eases open and closed with the pill's height. */}
        <ul
          className="dk-plist2"
          style={{ maxHeight: rows * ROW, opacity: listAlpha(openness) }}
          inert={!open}
        >
          {island.list.length === 0 ? (
            <li>
              <button className="dk-prow" onClick={openNest}>
                <Sprite mascot="nightshade" color={NIGHTSHADE} size={28} />
                <span className="dk-prb">
                  <span className="dk-prn">Nothing running</span>
                  <span className="dk-pra">Click to open Nest</span>
                </span>
              </button>
            </li>
          ) : (
            island.list.map((entry) => (
              <li key={entry.id}>
                <button
                  className="dk-prow"
                  onClick={() => {
                    click({ entry });
                  }}
                >
                  <Figure entry={entry} size={28} still />
                  <span className="dk-prb">
                    <span className="dk-prn">{entry.label}</span>
                    <span className="dk-pra">{entry.activity}</span>
                  </span>
                  <span className={`dk-prw t-${entry.status}`}>{STATUS_WORDS[entry.status]}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
      {/* Flights and their trails go under the strip, outside its shape. */}
      <div className="dk-pfree" aria-hidden="true">
        {flying.map((drawn) => (
          <span key={drawn.id} className="dk-pspr" style={{ left: drawn.x, top: drawn.y }}>
            <Art fig={drawn.data} still={false} flying />
          </span>
        ))}
      </div>
      <canvas ref={canvas} className="dk-pparticles" aria-hidden="true" />
    </>
  );
}

/** A sprite in its place on the strip: its button takes the strip's full height. */
function StripSprite({
  drawn,
  fig,
  left,
  onClick,
}: {
  drawn: DrawnSprite<Fig>;
  fig: Fig;
  left: number;
  onClick: (target: IslandTarget) => void;
}) {
  const spriteStyle = {
    top: drawn.y,
    opacity: drawn.alpha,
    transform: drawn.scale === 1 ? undefined : `scale(${String(drawn.scale)})`,
  };
  const art = (
    <span className="dk-pspr" style={spriteStyle}>
      <Art fig={fig} still={drawn.leaving} flying={false} />
      {!drawn.leaving && fig.kind === "entry" && <Badges entry={fig.entry} />}
      {fig.kind === "nightshade" && fig.mode === "asleep" && (
        <i className="dk-pz" aria-hidden="true" />
      )}
    </span>
  );
  // Leaving or folded into the +N: drawn, not clicked.
  if (drawn.leaving || drawn.hidden) {
    return (
      <span className="dk-pfig" style={{ left: left - 1 }} aria-hidden="true">
        {art}
      </span>
    );
  }
  if (fig.kind !== "entry") {
    const mode = fig.kind === "nightshade" ? fig.mode : fig.asleep ? "asleep" : "idle";
    return (
      <button
        className={`dk-pfig ${fig.kind === "nightshade" ? "dk-ns" : "dk-bb"} ${mode}`}
        style={{ left: left - 1 }}
        aria-label="Open Nest"
        onClick={() => {
          onClick({ strip: true });
        }}
      >
        {art}
      </button>
    );
  }
  const { entry } = fig;
  return (
    <button
      // Failed and interrupted show like needs you (D140); seen keeps its badge, calm.
      className={`dk-pfig s-${entry.status}${isAlert(entry.status) ? " alert" : ""}`}
      style={{ left: left - 1 }}
      aria-label={`${entry.label}, ${STATUS_WORDS[entry.status]}`}
      onClick={() => {
        onClick({ entry });
      }}
    >
      {art}
    </button>
  );
}

function Badges({ entry }: { entry: IslandEntry }) {
  return (
    <>
      {entry.status === "done" && (
        <>
          <i className="dk-ptick" aria-hidden="true">
            ✓
          </i>
          <i className="dk-psparks" aria-hidden="true" />
        </>
      )}
      {(isAlert(entry.status) || entry.status === "seen") && (
        <i className="dk-pbang" aria-hidden="true">
          !
        </i>
      )}
      {entry.status === "working" && (
        <i className="dk-prun" aria-hidden="true">
          <WorkingDot working />
        </i>
      )}
    </>
  );
}

/** A strip sprite's art: hopping while it works or flies, at rest while it leaves. */
function Art({ fig, still, flying }: { fig: Fig; still: boolean; flying: boolean }) {
  if (fig.kind === "nightshade") {
    return (
      <Sprite
        mascot="nightshade"
        color={NIGHTSHADE}
        size={SPRITE}
        working={!still && fig.mode === "working"}
        // Asleep its eyes stay shut (desktop.css).
        blink={fig.mode !== "working"}
      />
    );
  }
  if (fig.kind === "bluebell") {
    return <Sprite mascot="bluebell" color={BLUEBELL} size={SPRITE} blink />;
  }
  return <Figure entry={fig.entry} size={SPRITE} still={still} working={flying} />;
}

/** An entry's sprite or team: hopping on the strip while it works, at rest in the list. */
function Figure({
  entry,
  size,
  still = false,
  working = false,
}: {
  entry: IslandEntry;
  size: number;
  still?: boolean;
  // Hops whatever its state, as while it flies.
  working?: boolean;
}) {
  const { state } = useStore();
  const { figure } = entry;
  const hops = working || (!still && entry.status === "working");
  if ("team" in figure) {
    return (
      <TeamFace
        members={figure.members}
        pixies={state.pixies}
        className="dk-pteam"
        size={size / 2}
        working={hops}
      />
    );
  }
  return (
    <Sprite
      mascot={figure.pixie.mascot}
      color={figure.pixie.color}
      size={size}
      working={hops}
      phaseKey={entry.id}
    />
  );
}

/** The scene's sparks and trails: bursts inside the strip, trails anywhere. */
function drawParticles(canvas: HTMLCanvasElement | null, frame: SceneFrame) {
  if (canvas === null) return;
  const scale = window.devicePixelRatio;
  const width = window.innerWidth;
  const height = window.innerHeight;
  if (canvas.width !== Math.round(width * scale) || canvas.height !== Math.round(height * scale)) {
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
  }
  const context = canvas.getContext("2d");
  if (context === null) return;
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.clearRect(0, 0, width, height);
  if (frame.particles.length === 0) return;
  const centre = width / 2;
  const half = (frame.leftWidth + frame.rightWidth + 24) / 2;
  for (const free of [false, true]) {
    context.save();
    if (!free) {
      context.beginPath();
      context.rect(centre - half, 0, half * 2, STRIP);
      context.clip();
    }
    for (const particle of frame.particles) {
      if (particle.free !== free) continue;
      context.globalAlpha = Math.max(0, particle.life);
      context.fillStyle = particle.color;
      context.fillRect(
        Math.round(centre + particle.x),
        Math.round(particle.y),
        particle.size,
        particle.size,
      );
    }
    context.restore();
  }
}
