import { useState, type CSSProperties, type ReactNode } from "react";
import type { CallState, GroupEntry, Pixie, Session } from "../../../api/types.ts";
import { useStopTask } from "../../../screens/chat/useStopTask.ts";
import { useStore } from "../../../store/context.ts";
import { chatTree, type AgentNode } from "../../../store/selectors.ts";
import { leaderColor } from "../../../transcript/mentions.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Icon } from "../../../ui/Icon.tsx";
import { Sprite, TeamFace } from "../../pixies/Sprite.tsx";
import { Menu } from "../../ui/Menu.tsx";

/** Whose work a tree row opens: a pixie (or a team's member), or a whole team. */
export type WorkOf = { pixie: string } | { team: string };

const WORDS: Record<CallState, string> = {
  running: "working",
  done: "done",
  failed: "failed",
  interrupted: "stopped",
};

// One level of the tree's lines, in px (TreeGuides.step).
const STEP = 12;

interface Node {
  key: string;
  group: boolean;
  content: ReactNode;
  label: string;
  help?: string;
  open?: () => void;
  actions?: ReactNode;
  children: Node[];
}

interface Line {
  node: Node;
  depth: number;
  // For each level above, whether its line goes on past this row.
  guides: boolean[];
  last: boolean;
}

function flatten(nodes: Node[], depth = 0, guides: boolean[] = []): Line[] {
  return nodes.flatMap((node, index) => {
    const last = index === nodes.length - 1;
    return [
      { node, depth, guides, last },
      ...flatten(node.children, depth + 1, [...guides, !last]),
    ];
  });
}

interface Props {
  session: Session;
  onOpenAgent: (toolUseId: string) => void;
  onOpenWork: (who: WorkOf) => void;
}

/**
 * The tree under a chat in the sidebar, as the Mac's ChatTreeView (B46): "Pixies" with the
 * pixies and teams the chat called, then "Subagents" with those still working, joined by
 * tree lines. A row opens its work; on hover a pixie's or team's "…" has Send away, and a
 * subagent has Stop.
 */
export function ChatTree({ session, onOpenAgent, onOpenWork }: Props) {
  const { state, actions } = useStore();
  const stopper = useStopTask(session.id);
  const { pixies, subagents } = chatTree(state, session.id);
  if (pixies.length === 0 && subagents.length === 0) return null;
  const live = ["starting", "running", "waiting"].includes(session.state);

  const sendAway = (entry: GroupEntry, name: string) => (
    <Menu
      label={`Actions for ${name}`}
      align="end"
      items={[
        {
          title: "Send away",
          icon: "sendAway",
          detail:
            entry.kind === "team"
              ? "With its pixies; the next call starts fresh"
              : "The next call starts fresh",
          onSelect: () => {
            void actions.sendAway(
              session.id,
              entry.kind === "team"
                ? { team_id: String(entry.team_id) }
                : { pixie_id: String(entry.pixie_id) },
            );
          },
        },
      ]}
    >
      {(trigger) => (
        <button {...trigger} className="fr-more" aria-label={`Actions for ${name}`}>
          <Icon name="dots" />
        </button>
      )}
    </Menu>
  );

  const agentNodes = (nodes: AgentNode[]): Node[] =>
    nodes.map(({ agent, children }) => {
      const detail = agent.activity ?? agent.description;
      const stopping = stopper.stopping(agent.id);
      return {
        key: agent.id,
        group: false,
        label: `Subagent ${agent.name}, working`,
        help: `${agent.name}: ${agent.description ?? "working"}. Click to read its transcript.`,
        open: () => {
          onOpenAgent(agent.id);
        },
        actions:
          live && stopper.offered(agent.id) ? (
            <button
              className="fr-stop"
              disabled={stopping}
              title={stopping ? "Stopping" : "Stop"}
              aria-label={stopping ? "Stopping" : `Stop ${agent.name}`}
              onClick={() => {
                stopper.stop(agent.id);
              }}
            >
              <Icon name="stop" />
            </button>
          ) : undefined,
        content: (
          <>
            <span className="fr-tic">
              <Fireflies size={9} />
            </span>
            <span className="fr-tname">{agent.name}</span>
            {detail !== null && <span className="fr-tdetail">{detail}</span>}
          </>
        ),
        children: agentNodes(children),
      };
    });

  const entryNode = (entry: GroupEntry): Node => {
    if (entry.kind === "pixie") {
      const pixie = state.pixies[String(entry.pixie_id)];
      const name = pixie?.name ?? "A pixie";
      return {
        key: `pixie-${String(entry.pixie_id)}`,
        group: false,
        label: `Pixie ${name}, ${WORDS[entry.state]}`,
        help: `Open ${name}'s work in this chat`,
        open: () => {
          onOpenWork({ pixie: String(entry.pixie_id) });
        },
        actions: sendAway(entry, name),
        content: (
          <>
            <Face pixie={pixie} working={entry.state === "running"} size={12} />
            <span
              className="fr-tname"
              style={pixie === undefined ? undefined : { color: pixie.color }}
            >
              {name}
            </span>
            <span className="grow" />
            <StateMark state={entry.state} />
          </>
        ),
        children: [],
      };
    }
    const team = state.teams[String(entry.team_id)];
    const name = team?.name ?? "A team";
    const color = team === undefined ? null : leaderColor(team, state.pixies);
    const tint: CSSProperties | undefined = color === null ? undefined : { color };
    return {
      key: `team-${String(entry.team_id)}`,
      group: false,
      label: `Team ${name}${team === undefined ? "" : `, @${team.handle}`}, ${WORDS[entry.state]}`,
      help: `Open ${name}'s work in this chat`,
      open: () => {
        onOpenWork({ team: String(entry.team_id) });
      },
      actions: sendAway(entry, name),
      content: (
        <>
          <span className="fr-tic" style={tint}>
            {entry.members.length > 0 ? (
              <TeamFace
                members={entry.members}
                pixies={state.pixies}
                className="fr-team"
                size={7}
              />
            ) : (
              <Icon name="user" />
            )}
          </span>
          <span className="fr-tname team" style={tint}>
            {name}
          </span>
          {team !== undefined && <span className="fr-tdetail">@{team.handle}</span>}
          <span className="grow" />
          <StateMark state={entry.state} />
        </>
      ),
      children: entry.members.map((member) => {
        const pixie = state.pixies[member.pixie_id];
        const who = pixie?.name ?? "A pixie";
        return {
          key: `member-${member.pixie_id}`,
          group: false,
          label: `${who}${member.leader ? ", leader" : ""}, ${member.state === null ? "not called yet" : WORDS[member.state]}`,
          help: `Open ${who}'s work in this chat`,
          open: () => {
            onOpenWork({ pixie: member.pixie_id });
          },
          content: (
            <>
              <Face pixie={pixie} working={member.state === "running"} size={11} />
              <span className="fr-tname">{who}</span>
              {member.leader && <span className="fr-lead">Leader</span>}
              <span className="grow" />
              <StateMark state={member.state} />
            </>
          ),
          children: [],
        };
      }),
    };
  };

  const roots: Node[] = [];
  if (pixies.length > 0) {
    roots.push({
      key: "pixies",
      group: true,
      label: "Pixies",
      content: "Pixies",
      children: pixies.map(entryNode),
    });
  }
  if (subagents.length > 0) {
    roots.push({
      key: "subagents",
      group: true,
      label: "Subagents",
      content: "Subagents",
      children: agentNodes(subagents),
    });
  }
  return (
    <div className="fr-tree" role="list" aria-label={`Working in ${session.title}`}>
      {flatten(roots).map((line) => (
        <TreeLine key={line.node.key} line={line} />
      ))}
    </div>
  );
}

function TreeLine({ line }: { line: Line }) {
  const [hovering, setHovering] = useState(false);
  const { node } = line;
  const height = node.group ? 20 : 24;
  const width = STEP * (line.depth + 1);
  const mid = Math.round(height / 2) + 0.5;
  const x = (level: number) => STEP * level + 4.5;
  const elbow = x(line.guides.length);
  return (
    <div
      className={node.group ? "fr-tline group" : "fr-tline"}
      role="listitem"
      style={{ height }}
      onPointerEnter={() => {
        setHovering(true);
      }}
      onPointerLeave={() => {
        setHovering(false);
      }}
    >
      <svg className="fr-guides" width={width} height={height} aria-hidden="true">
        {line.guides.map((goes, level) =>
          goes ? <line key={level} x1={x(level)} x2={x(level)} y1={0} y2={height} /> : null,
        )}
        <path
          d={`M${String(elbow)} 0V${String(line.last ? mid : height)}M${String(elbow)} ${String(mid)}H${String(elbow + STEP - 3)}`}
        />
      </svg>
      {node.group ? (
        <span className="fr-tgroup">{node.content}</span>
      ) : (
        <span className={hovering ? "fr-trow on" : "fr-trow"}>
          <button className="fr-tb" aria-label={node.label} title={node.help} onClick={node.open}>
            {node.content}
          </button>
          {node.actions !== undefined && <span className="fr-tacts">{node.actions}</span>}
        </span>
      )}
    </div>
  );
}

function Face({
  pixie,
  working,
  size,
}: {
  pixie: Pixie | undefined;
  working: boolean;
  size: number;
}) {
  return (
    <span className="fr-tic" aria-hidden="true">
      {pixie !== undefined && (
        <Sprite
          mascot={pixie.mascot}
          color={pixie.color}
          size={size}
          working={working}
          phaseKey={pixie.id}
        />
      )}
    </span>
  );
}

/** A call's state at a row's end: fireflies while it works, else its word. */
function StateMark({ state }: { state: CallState | null }) {
  if (state === "running") return <Fireflies size={9} />;
  return (
    <span className={state === "failed" ? "fr-tword bad" : "fr-tword"}>
      {state === null ? "not called yet" : WORDS[state]}
    </span>
  );
}
