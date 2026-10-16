import { useState, type CSSProperties, type ReactNode } from "react";
import type { Mascot, Pixie, PixieTeam } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { pixieList, pixieWorking, teamList, unreadActions } from "../../store/selectors.ts";
import { leaderColor } from "../../transcript/mentions.ts";
import { Icon } from "../../ui/Icon.tsx";
import { useRowGestures } from "../projects/rowGestures.ts";
import { NameSheet } from "./NameSheet.tsx";
import { usePending } from "./pending.ts";
import { actionText } from "./options.ts";
import { PixieActions } from "./PixieActions.tsx";
import type { PixieTab } from "./PixieView.tsx";
import { Sprite } from "./Sprite.tsx";
import { TeamActions } from "./TeamActions.tsx";

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

// A team's section, or the pixies in no team (team null), each in list order.
interface Group {
  team: PixieTeam | null;
  pixies: Pixie[];
}

type Menu = { pixie: string } | { team: string } | "newTeam";

/**
 * The user's pixies above the projects, each opening its page, and New pixie. Teams are
 * foldable sections with their pixies, those in no team below (B40). Each row and team
 * header has a menu. Edit order turns the rows into up and down buttons: a long-press drag
 * fights the page's scrolling and Safari's text selection on a touch screen, and buttons
 * work with VoiceOver too.
 */
export function PixieSection({ onOpen }: Props) {
  const { state, actions } = useStore();
  const [showHidden, setShowHidden] = useState(false);
  const [ordering, setOrdering] = useState(false);
  const [menu, setMenu] = useState<Menu | null>(null);
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
  // Unread action reports of the pixies (B42).
  const alerts = unreadActions(state);
  const teams = teamList(state);
  const groups: Group[] = [
    ...teams.map((team) => ({ team, pixies: pixies.filter((p) => p.team_id === team.id) })),
    // A pixie whose team is not known (yet) shows with those in no team.
    { team: null, pixies: pixies.filter((p) => p.team_id === null || !(p.team_id in state.teams)) },
  ];
  const closeMenu = () => {
    setMenu(null);
  };

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

  /** Moves pixie `id` past `other`, its neighbour in its section. */
  const moveNextTo = (id: string, other: Pixie, after: boolean) => () => {
    place(id, other.id, after);
  };

  const rows = (group: Group) =>
    group.pixies.map((p, index) => {
      const before = group.pixies[index - 1];
      const after = group.pixies[index + 1];
      return ordering ? (
        <OrderRow key={p.id} pixie={p} before={before} after={after} place={place} />
      ) : (
        <PixieRow
          key={p.id}
          pixie={p}
          leader={group.team?.leader_id === p.id}
          running={pixieWorking(state, p)}
          alerts={unreadActions(state, p.id)}
          onOpen={onOpen}
          onActions={() => {
            setMenu({ pixie: p.id });
          }}
        />
      );
    });

  const acting = menu !== null && typeof menu === "object" && "pixie" in menu ? menu.pixie : null;
  const actingRow = acting === null ? null : rowOf(groups, acting);
  const teamMenu =
    menu !== null && typeof menu === "object" && "team" in menu
      ? state.teams[menu.team]
      : undefined;

  return (
    <section className="pxsec" aria-labelledby="pixies-title">
      <h2 className="pg-h" id="pixies-title">
        Pixies
        <span className="gc">{pixies.length}</span>
        {alerts > 0 && (
          <span className="pxalert" aria-label={actionText(alerts)}>
            {alerts}
          </span>
        )}
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
      {groups.map(({ team, pixies: members }) =>
        team === null ? (
          <section key="none" className="lgrp gl" aria-label="No team">
            {rows({ team, pixies: members })}
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
                <button
                  className="pxnewt"
                  aria-haspopup="dialog"
                  onClick={() => {
                    setMenu("newTeam");
                  }}
                >
                  New team
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
          </section>
        ) : (
          <TeamSection
            key={team.id}
            team={team}
            color={leaderColor(team, state.pixies)}
            count={members.length}
            folded={state.foldedTeams.includes(team.id)}
            onFold={(folded) => {
              actions.setTeamFolded(team.id, folded);
            }}
            onActions={() => {
              setMenu({ team: team.id });
            }}
          >
            {rows({ team, pixies: members })}
          </TeamSection>
        ),
      )}
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
      {actingRow !== null && (
        <PixieActions
          pixie={actingRow.pixie}
          teams={teams}
          onMoveUp={
            actingRow.before === undefined
              ? null
              : moveNextTo(actingRow.pixie.id, actingRow.before, false)
          }
          onMoveDown={
            actingRow.after === undefined
              ? null
              : moveNextTo(actingRow.pixie.id, actingRow.after, true)
          }
          onOpen={onOpen}
          onClose={closeMenu}
        />
      )}
      {teamMenu !== undefined && (
        <TeamActions
          team={teamMenu}
          members={pixieList(state, true).filter((p) => p.team_id === teamMenu.id)}
          onClose={closeMenu}
        />
      )}
      {menu === "newTeam" && (
        <NameSheet
          title="New team"
          label="Team name"
          empty="Type a name"
          initial=""
          action="Create"
          onSave={(name) => {
            void actions.createTeam(name).then((created) => {
              if (created !== null) closeMenu();
            });
          }}
          onClose={closeMenu}
        />
      )}
    </section>
  );
}

/** The pixie `id` in its section, with the pixies shown above and below it there. */
function rowOf(groups: Group[], id: string) {
  for (const { pixies } of groups) {
    for (const [index, pixie] of pixies.entries()) {
      if (pixie.id === id) return { pixie, before: pixies[index - 1], after: pixies[index + 1] };
    }
  }
  return null;
}

interface TeamSectionProps {
  team: PixieTeam;
  // Its leader's colour, for its name.
  color: string | null;
  // Its pixies shown.
  count: number;
  folded: boolean;
  onFold: (folded: boolean) => void;
  onActions: () => void;
  children: ReactNode;
}

/** A team's header, folding its pixies away, with its menu; then its pixies. */
function TeamSection({
  team,
  color,
  count,
  folded,
  onFold,
  onActions,
  children,
}: TeamSectionProps) {
  const id = `team-${team.id}`;
  return (
    <section className="pxteam" aria-labelledby={id}>
      <div className="pxth">
        <button
          className="pg-h pgb"
          aria-expanded={!folded}
          onClick={() => {
            onFold(!folded);
          }}
        >
          <Icon name="chev" className="cv" />
          {color === null ? (
            <span id={id}>{team.name}</span>
          ) : (
            <span id={id} className="pxtname" style={{ "--px": color } as CSSProperties}>
              {team.name}
            </span>
          )}
          <span className="pxhandle">@{team.handle}</span>
          <span className="gc">{count}</span>
        </button>
        <button className="rmore" aria-label={`Actions for team ${team.name}`} onClick={onActions}>
          <Icon name="dots" />
        </button>
      </div>
      {!folded && (
        <div className="lgrp gl">
          {count === 0 ? <p className="pxnone">No pixies yet</p> : children}
        </div>
      )}
    </section>
  );
}

interface RowProps {
  pixie: Pixie;
  leader: boolean;
  // At work in its own chat or on a call in any chat (B48).
  running: boolean;
  // Its unread action reports.
  alerts: number;
  onOpen: (id: string, tab: PixieTab) => void;
  onActions: () => void;
}

/** A pixie: tap opens it; long-press, swipe left or the dots button show its menu. */
function PixieRow({ pixie: p, leader, running, alerts, onOpen, onActions }: RowProps) {
  const gestures = useRowGestures(() => {
    onOpen(p.id, "chat");
  }, onActions);
  return (
    <div className="lrow">
      <button
        className="row pxr"
        aria-label={`${p.name}, @${p.slug}${leader ? ", leader" : ""}${running ? ", running" : ""}${alerts > 0 ? `, ${actionText(alerts)}` : ""}`}
        data-chat={`pixie:${p.id}`}
        {...gestures}
      >
        <Sprite mascot={p.mascot} color={p.color} size={28} working={running} phaseKey={p.id} />
        <span className="rt">{p.name}</span>
        {(leader || running || alerts > 0) && (
          <span className="rm">
            {leader && <span className="pxlead">Leader</span>}
            {running && <span className="prun" />}
            {alerts > 0 && (
              <span className="pxalert" aria-hidden="true">
                {alerts}
              </span>
            )}
          </span>
        )}
        <span className="rm pxslug">@{p.slug}</span>
        <Icon name="chevr" className="chv" />
      </button>
      <button className="rmore" aria-label={`Actions for ${p.name}`} onClick={onActions}>
        <Icon name="dots" />
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
