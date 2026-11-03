// The pill's moving parts, ported from the Mac's IslandScene.render (B114; B117 here): each
// side's width eases toward its fit, the strip grows into the list, every pixie eases to its
// place, drops in from above when it first shows, flies under the strip with a trail when it
// changes side and lands with a burst, folds into the +N, and fades up and away when it
// leaves, or pops when a click sent it away. Times are milliseconds and lengths CSS pixels,
// x from the pill's centre and y from its top. The per-state poses (hops, blinks, the done
// spin) stay CSS animations on each sprite (desktop.css).
import { macEase, OPEN_RATE } from "./pillMotion.ts";

// IslandLayout and IslandScene.
export const SPRITE = 28;
export const SLOT = 30;
export const PAD = 8;
const PILL_GAP = 12;
export const STRIP_HEIGHT = 34;
export const SPRITE_TOP = Math.round((STRIP_HEIGHT - SPRITE) / 2);
// A flight under the strip takes this long.
export const FLIGHT_MS = 1300;
// A pixie that leaves fades for this long; a popped one goes at once.
export const LEAVE_MS = 300;
// A pop is remembered this long, so a pixie leaving soon after its click pops.
const POPPED_MS = 2000;
// Each side's width closes 7 times its distance a second, a sprite's place 9 times.
const WIDTH_RATE = 7;
const PLACE_RATE = 9;
// How far below the strip's top a flight dips: the strip's height and 14.
export const DIP = STRIP_HEIGHT + 14;
// Room below the strip the window needs while something flies there (the lowest sprite
// and its trail).
export const FLIGHT_ROOM = DIP + SPRITE + 8;

const ORANGE = "#F5A524";
const SPARK = "#FFE08A";

export type Side = "left" | "right";
/** What a pixie does, for its landing: a done one bursts in its colour, one needing you in orange. */
export type Landing = "done" | "alert" | "none";

export interface SceneItem<T = unknown> {
  id: string;
  color: string;
  landing: Landing;
  // What the page draws for it, kept while it leaves.
  data: T;
}

export interface SceneInput<T = unknown> {
  left: SceneItem<T>[];
  right: SceneItem<T>[];
  // Each side's width once eased (the pill keeps both sides even).
  sideWidth: number;
  wantsOpen: boolean;
  reduce: boolean;
}

export interface Particle {
  x: number;
  y: number;
  // Pixels a second.
  vx: number;
  vy: number;
  life: number;
  // Life lost a second.
  decay: number;
  color: string;
  size: number;
  // A trail: drawn under the strip, outside its shape.
  free: boolean;
}

export interface DrawnSprite<T = unknown> {
  id: string;
  data: T;
  side: Side;
  x: number;
  y: number;
  alpha: number;
  scale: number;
  flying: boolean;
  leaving: boolean;
  // Folded into the +N.
  hidden: boolean;
  // When it landed in its place (the done spin starts there).
  arrived: number;
}

export interface SceneFrame<T = unknown> {
  leftWidth: number;
  rightWidth: number;
  // 0 closed to 1 open, and its ease.
  open: number;
  eased: number;
  sprites: DrawnSprite<T>[];
  particles: Particle[];
  // Something still moves: the next frame differs.
  moving: boolean;
  // Something flies or sparks below the strip.
  under: boolean;
}

interface Flight {
  start: number;
  x: number;
  y: number;
}

interface Sprite<T> {
  data: T;
  color: string;
  x: number;
  y: number;
  side: Side;
  flight: Flight | null;
  arrived: number;
  alpha: number;
  leaving: number | null;
}

interface Want<T> {
  item: SceneItem<T>;
  side: Side;
  x: number;
  y: number;
  hidden: boolean;
}

export interface Scene<T> {
  step(t: number, input: SceneInput<T>): SceneFrame<T>;
  // A click sent this pixie away: it pops as it leaves, if it leaves soon.
  pop(id: string): void;
}

/** Where each side's +N is drawn, beside the side's shown pixies. */
export function plusX(side: Side, width: number, shown: number): number {
  return side === "left"
    ? -PILL_GAP - width + PAD + shown * SLOT + 3
    : PILL_GAP + PAD + shown * SLOT + 5;
}

export function createScene<T>(random: () => number = Math.random): Scene<T> {
  let leftWidth: number | null = null;
  let rightWidth: number | null = null;
  let open = 0;
  let last: number | null = null;
  const sprites = new Map<string, Sprite<T>>();
  const popped = new Map<string, number>();
  let particles: Particle[] = [];

  const burst = (x: number, y: number, color: string, count: number, speed: number) => {
    for (let index = 0; index < count; index++) {
      const angle = random() * 2 * Math.PI;
      const velocity = (0.5 + random()) * speed * 60;
      particles.push({
        x,
        y,
        vx: Math.cos(angle) * velocity,
        vy: Math.sin(angle) * velocity * 0.5,
        life: 1,
        decay: 0.07 * 60,
        color: index % 3 !== 0 ? SPARK : color,
        size: 2,
        free: false,
      });
    }
  };
  // Two specks a frame at 60 frames a second behind a flying sprite, which fade at once.
  const trail = (sprite: Sprite<T>, dt: number) => {
    const count = 120 * dt;
    let spawn = Math.floor(count);
    if (random() < count - spawn) spawn += 1;
    for (let index = 0; index < spawn; index++) {
      particles.push({
        x: sprite.x + SPRITE / 2 + (random() * 8 - 4),
        y: sprite.y + SPRITE * 0.55 + (random() * 6 - 3),
        vx: 0,
        vy: 0,
        life: 1,
        decay: 0.035 * 60,
        color: random() < 0.5 ? sprite.color : SPARK,
        size: 2,
        free: true,
      });
    }
  };

  const wants = (input: SceneInput<T>, left: number): Want<T>[] => {
    const list: Want<T>[] = [];
    const place = (items: SceneItem<T>[], side: Side, start: number, plus: number) => {
      const shown = Math.min(3, items.length);
      items.forEach((item, index) => {
        const hidden = index >= shown;
        list.push({
          item,
          side,
          x: hidden ? plus : start + PAD + index * SLOT,
          y: SPRITE_TOP,
          hidden,
        });
      });
    };
    const shownLeft = Math.min(3, input.left.length);
    const shownRight = Math.min(3, input.right.length);
    place(input.left, "left", -PILL_GAP - left, -PILL_GAP - left + PAD + shownLeft * SLOT - 4);
    place(input.right, "right", PILL_GAP, PILL_GAP + PAD + shownRight * SLOT - 2);
    return list;
  };

  return {
    pop(id) {
      popped.set(id, last ?? 0);
    },
    step(t, input) {
      const dt = Math.min(0.05, Math.max(0, (t - (last ?? t)) / 1000));
      last = t;
      const reduce = input.reduce;
      let moving = false;

      // Each side's width.
      const widthStep = reduce ? 1 : Math.min(1, dt * WIDTH_RATE);
      leftWidth ??= input.sideWidth;
      rightWidth ??= input.sideWidth;
      leftWidth += (input.sideWidth - leftWidth) * widthStep;
      rightWidth += (input.sideWidth - rightWidth) * widthStep;
      if (
        Math.abs(leftWidth - input.sideWidth) > 0.05 ||
        Math.abs(rightWidth - input.sideWidth) > 0.05
      ) {
        moving = true;
      } else {
        leftWidth = input.sideWidth;
        rightWidth = input.sideWidth;
      }

      // The strip grows into the list.
      const target = input.wantsOpen ? 1 : 0;
      open += (target - open) * (reduce ? 1 : Math.min(1, dt * OPEN_RATE));
      if (Math.abs(open - target) < 0.002) open = target;
      else moving = true;

      const wanted = wants(input, leftWidth);
      const ids = new Set(wanted.map((w) => w.item.id));
      const drawn: DrawnSprite<T>[] = [];

      // Those that left: a pop bursts and goes, the rest fade up for 300 ms.
      for (const [id, sprite] of sprites) {
        if (ids.has(id)) continue;
        const pops = popped.has(id);
        if (pops && !reduce) burst(sprite.x + 14, sprite.y + 14, sprite.color, 22, 2.2);
        sprite.leaving ??= t;
        if (pops || t - sprite.leaving > LEAVE_MS) {
          sprites.delete(id);
          popped.delete(id);
          continue;
        }
        moving = true;
        const alpha = 1 - (t - sprite.leaving) / LEAVE_MS;
        drawn.push({
          id,
          data: sprite.data,
          side: sprite.side,
          x: sprite.x,
          y: sprite.y - (1 - alpha) * 8,
          alpha,
          scale: 1,
          flying: false,
          leaving: true,
          hidden: false,
          arrived: sprite.arrived,
        });
      }
      for (const [id, at] of popped) if (t - at >= POPPED_MS) popped.delete(id);

      for (const want of wanted) {
        const { item } = want;
        let sprite = sprites.get(item.id);
        if (sprite === undefined) {
          // A new one drops in from above the strip.
          sprite = {
            data: item.data,
            color: item.color,
            x: want.x,
            y: reduce ? want.y : -SPRITE - 4,
            side: want.side,
            flight: null,
            arrived: t,
            alpha: 1,
            leaving: null,
          };
          sprites.set(item.id, sprite);
        }
        sprite.data = item.data;
        sprite.color = item.color;
        sprite.leaving = null;
        if (sprite.side !== want.side) {
          sprite.side = want.side;
          if (reduce) {
            sprite.x = want.x;
            sprite.y = want.y;
            sprite.arrived = t;
          } else {
            sprite.flight = { start: t, x: sprite.x, y: sprite.y };
          }
        }
        let flying = false;
        if (sprite.flight !== null) {
          const { flight } = sprite;
          const progress = Math.min(1, (t - flight.start) / FLIGHT_MS);
          const eased = macEase(progress);
          sprite.x = flight.x + (want.x - flight.x) * eased;
          sprite.y =
            flight.y +
            (want.y - flight.y) * eased +
            Math.sin(progress * Math.PI) * (DIP - Math.min(flight.y, want.y));
          flying = true;
          moving = true;
          trail(sprite, dt);
          if (progress >= 1) {
            sprite.flight = null;
            sprite.arrived = t;
            flying = false;
            if (item.landing === "done") {
              burst(sprite.x + SPRITE / 2, sprite.y + SPRITE / 2, item.color, 10, 1.2);
            } else if (item.landing === "alert") {
              burst(sprite.x + SPRITE / 2, sprite.y + SPRITE / 2, ORANGE, 6, 1);
            }
          }
        } else {
          const step = reduce ? 1 : Math.min(1, dt * PLACE_RATE);
          sprite.x += (want.x - sprite.x) * step;
          sprite.y += (want.y - sprite.y) * step;
          if (Math.abs(want.x - sprite.x) > 0.05 || Math.abs(want.y - sprite.y) > 0.05) {
            moving = true;
          } else {
            sprite.x = want.x;
            sprite.y = want.y;
          }
        }
        if (flying) {
          sprite.alpha = 1;
        } else {
          const near = Math.abs(sprite.x - want.x) < 3 && Math.abs(sprite.y - want.y) < 3;
          const alpha = want.hidden && near ? 0 : 1;
          sprite.alpha +=
            (alpha - sprite.alpha) * (reduce ? 1 : Math.min(1, dt * (want.hidden ? 8 : 6)));
          if (Math.abs(alpha - sprite.alpha) > 0.01) moving = true;
          else sprite.alpha = alpha;
        }
        // One folded into the +N is not drawn.
        if (want.hidden && sprite.alpha < 0.03) continue;
        drawn.push({
          id: item.id,
          data: item.data,
          side: want.side,
          x: sprite.x,
          y: sprite.y,
          alpha: sprite.alpha,
          scale: want.hidden ? 0.6 + 0.4 * sprite.alpha : 1,
          flying,
          leaving: false,
          hidden: want.hidden,
          arrived: sprite.arrived,
        });
      }

      // Particles move, fade and go.
      for (const particle of particles) {
        particle.x += particle.vx * dt;
        particle.y += particle.vy * dt;
        particle.life -= particle.decay * dt;
      }
      particles = particles.filter((p) => p.life > 0);
      if (particles.length > 0) moving = true;
      const under = drawn.some((s) => s.flying) || particles.some((p) => p.free);

      return {
        leftWidth,
        rightWidth,
        open,
        eased: macEase(open),
        sprites: drawn,
        particles: particles.map((p) => ({ ...p })),
        moving,
        under,
      };
    },
  };
}

/**
 * How a pixie that is no longer on the pill goes: a finished one whose chat was seen after
 * it finished pops (a click or the focused chat sent it away, IslandController.see), any
 * other fades.
 */
export function leaving(status: string, since: number, seenAt: number | undefined): "pop" | "fade" {
  const finished = status === "done" || status === "failed" || status === "interrupted";
  return finished && seenAt !== undefined && seenAt >= since ? "pop" : "fade";
}
