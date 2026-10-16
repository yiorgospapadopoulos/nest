import { useState, type CSSProperties, type ReactNode } from "react";
import type { CallState, GroupEntry, Pixie, Session, TeamMember } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { chatTree, type AgentNode } from "../../store/selectors.ts";
import { leaderColor } from "../../transcript/mentions.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";
import { Sprite } from "../pixies/Sprite.tsx";
import { TeamFace } from "../pixies/TeamFace.tsx";

/** Whose work a tree row opens: a pixie (or a team's member), or a whole team. */
export type WorkOf = { pixie: string } | { team: string };

const STATE_WORDS: Record<CallState, string> = {
  running: "working",
  done: "done",
  failed: "failed",
  interrupted: "stopped",
};

interface Props {
  session: Session;
  onOpenAgent: (toolUseId: string) => void;
  onOpenWork: (who: WorkOf) => void;
}

/**
 * Under a chat's row, joined to it by tree lines (B46): the pixies and teams it called,
 * which stay once finished, and its subagents while they run, each under the subagent
 * that started it. Nothing shows while the chat has neither.
 */
export function ChatTree({ session, onOpenAgent, onOpenWork }: Props) {
  const { state } = useStore();
  const [menu, setMenu] = useState<GroupEntry | null>(null);
  const { pixies, subagents } = chatTree(state, session.id);
  if (pixies.length === 0 && subagents.length === 0) return null;

  const agentRows = (nodes: AgentNode[]) =>
    nodes.map(({ agent, children }) => (
      <li key={agent.id}>
        <Row
          label={[agent.name, agent.description, "working"].filter(Boolean).join(", ")}
          onOpen={() => {
            onOpenAgent(agent.id);
          }}
        >
          <span className="spin" aria-hidden="true" />
          <span className="ctn">{agent.name}</span>
          {agent.description !== null && <span className="ctd">{agent.description}</span>}
        </Row>
        {children.length > 0 && <ul>{agentRows(children)}</ul>}
      </li>
    ));

  return (
    <>
      <ul className="ctree" aria-label={`Working in ${session.title}`}>
        {pixies.length > 0 && (
          <li>
            <span className="ctg" id={`ct-px-${session.id}`}>
              Pixies
            </span>
            <ul role="group" aria-labelledby={`ct-px-${session.id}`}>
              {pixies.map((entry) => (
                <EntryRow
                  key={entry.team_id ?? entry.pixie_id}
                  entry={entry}
                  chat={session.title}
                  onOpen={onOpenWork}
                  onActions={() => {
                    setMenu(entry);
                  }}
                />
              ))}
            </ul>
          </li>
        )}
        {subagents.length > 0 && (
          <li>
            <span className="ctg" id={`ct-sa-${session.id}`}>
              Subagents
            </span>
            <ul role="group" aria-labelledby={`ct-sa-${session.id}`}>
              {agentRows(subagents)}
            </ul>
          </li>
        )}
      </ul>
      {menu !== null && (
        <SendAway
          sessionId={session.id}
          entry={menu}
          onClose={() => {
            setMenu(null);
          }}
        />
      )}
    </>
  );
}

interface EntryProps {
  entry: GroupEntry;
  // The chat's title, which names the row's menu apart from the pixie list's.
  chat: string;
  onOpen: (who: WorkOf) => void;
  onActions: () => void;
}

/** A solo pixie, or a team in its leader's colour with its members under it. */
function EntryRow({ entry, chat, onOpen, onActions }: EntryProps) {
  const { state } = useStore();
  const name = entryName(entry, state.pixies, state.teams);
  const more = (
    <button
      className="rmore ctm"
      aria-label={`Actions for ${entry.kind === "team" ? "team " : ""}${name} in ${chat}`}
      onClick={onActions}
    >
      <Icon name="dots" />
    </button>
  );
  if (entry.kind === "pixie") {
    const pixie = state.pixies[String(entry.pixie_id)];
    return (
      <li>
        <Row
          label={`${name}, ${STATE_WORDS[entry.state]}`}
          onOpen={() => {
            onOpen({ pixie: String(entry.pixie_id) });
          }}
          more={more}
        >
          <PixieFace pixie={pixie} working={entry.state === "running"} />
          <span className="ctn">{name}</span>
          <CallMark state={entry.state} />
        </Row>
      </li>
    );
  }
  const team = state.teams[String(entry.team_id)];
  const color = team === undefined ? null : leaderColor(team, state.pixies);
  // The team's mark and name take its leader's colour (B45).
  const tint = color === null ? undefined : ({ "--px": color } as CSSProperties);
  const tinted = color === null ? "" : " pxtname";
  const handle = team === undefined ? "" : `, @${team.handle}`;
  return (
    <li>
      <Row
        label={`${name}${handle}, ${STATE_WORDS[entry.state]}`}
        onOpen={() => {
          onOpen({ team: String(entry.team_id) });
        }}
        more={more}
      >
        {entry.members.length > 0 ? (
          <TeamFace
            members={entry.members}
            pixies={state.pixies}
            className="ctic ctteam"
            size={10}
          />
        ) : (
          <span className={`ctic${tinted}`} style={tint} aria-hidden="true">
            <Icon name="user" />
          </span>
        )}
        <span className={`ctn${tinted}`} style={tint}>
          {name}
        </span>
        {team !== undefined && <span className="pxhandle">@{team.handle}</span>}
        <CallMark state={entry.state} />
      </Row>
      <ul>
        {entry.members.map((member) => (
          <MemberRow key={member.pixie_id} member={member} onOpen={onOpen} />
        ))}
      </ul>
    </li>
  );
}

function MemberRow({ member, onOpen }: { member: TeamMember; onOpen: (who: WorkOf) => void }) {
  const { state } = useStore();
  const pixie = state.pixies[member.pixie_id];
  const name = pixie?.name ?? "A pixie";
  const word = member.state === null ? "not called yet" : STATE_WORDS[member.state];
  return (
    <li>
      <Row
        label={`${name}${member.leader ? ", leader" : ""}, ${word}`}
        onOpen={() => {
          onOpen({ pixie: member.pixie_id });
        }}
      >
        <PixieFace pixie={pixie} working={member.state === "running"} />
        <span className="ctn">{name}</span>
        {member.leader && <span className="pxlead">Leader</span>}
        {member.state === null ? (
          <span className="ctw">{word}</span>
        ) : (
          <CallMark state={member.state} />
        )}
      </Row>
    </li>
  );
}

interface RowProps {
  label: string;
  onOpen: () => void;
  more?: ReactNode;
  children: ReactNode;
}

function Row({ label, onOpen, more, children }: RowProps) {
  return (
    <div className="ctr">
      <button className="ctb" aria-label={label} onClick={onOpen}>
        {children}
      </button>
      {more}
    </div>
  );
}

/** A pixie's sprite, hopping while its call runs; the row's working dot says so too. */
function PixieFace({ pixie, working }: { pixie: Pixie | undefined; working: boolean }) {
  return (
    <span className="ctic" aria-hidden="true">
      {pixie !== undefined && (
        <Sprite
          mascot={pixie.mascot}
          color={pixie.color}
          size={18}
          working={working}
          phaseKey={pixie.id}
        />
      )}
    </span>
  );
}

/** A call's state: a working dot while it runs, else its word. */
function CallMark({ state }: { state: CallState }) {
  return state === "running" ? (
    <span className="prun" aria-hidden="true" />
  ) : (
    <span className={state === "failed" ? "ctw bad" : "ctw"}>{STATE_WORDS[state]}</span>
  );
}

function entryName(
  entry: GroupEntry,
  pixies: Record<string, Pixie>,
  teams: Record<string, { name: string }>,
): string {
  return entry.kind === "team"
    ? (teams[String(entry.team_id)]?.name ?? "A team")
    : (pixies[String(entry.pixie_id)]?.name ?? "A pixie");
}

interface SendAwayProps {
  sessionId: string;
  entry: GroupEntry;
  onClose: () => void;
}

/** A pixie's or team's menu in a chat's tree: Send away (B46). */
function SendAway({ sessionId, entry, onClose }: SendAwayProps) {
  const { state, actions } = useStore();
  const name = entryName(entry, state.pixies, state.teams);
  const send = async () => {
    const body =
      entry.kind === "team"
        ? { team_id: String(entry.team_id) }
        : { pixie_id: String(entry.pixie_id) };
    if (await actions.sendAway(sessionId, body)) onClose();
  };
  return (
    <ActionSheet label={name} title={name} onClose={onClose}>
      <button className="asi" role="menuitem" onClick={() => void send()}>
        <span>
          Send away
          <small>
            {entry.kind === "team"
              ? "With its pixies; the next call starts fresh"
              : "The next call starts fresh"}
          </small>
        </span>
      </button>
    </ActionSheet>
  );
}
