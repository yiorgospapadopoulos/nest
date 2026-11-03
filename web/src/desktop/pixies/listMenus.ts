// The Pixies list's menus, under ⋯ and on a right click, with the Mac's entries
// (PixieList.swift's PixieActions and TeamActions).
import type { Pixie, PixieTeam } from "../../api/types.ts";
import { separator, type MenuEntry } from "../ui/menuItems.ts";
import type { TeamSection } from "./order.ts";

export interface PixieMenuActions {
  open: () => void;
  details: () => void;
  duplicate: () => void;
  // A team's id, or null for No team.
  setTeam: (team: string | null) => void;
  move: (offset: -1 | 1) => void;
  setHidden: (hidden: boolean) => void;
  remove: () => void;
}

/** Open, Details, Duplicate, Move to team, Move Up, Move Down, Hide or Show, Delete. */
export function pixieMenu(
  pixie: Pixie,
  // The ids of the pixies in its section, in order.
  listed: string[],
  teams: PixieTeam[],
  act: PixieMenuActions,
): MenuEntry[] {
  const teamItems: MenuEntry[] = teams.map((team) => ({
    title: team.name,
    checked: pixie.team_id === team.id,
    onSelect: () => {
      act.setTeam(team.id);
    },
  }));
  return [
    { title: "Open", icon: "open", onSelect: act.open },
    { title: "Details", icon: "panel", onSelect: act.details },
    { title: "Duplicate", icon: "copy", onSelect: act.duplicate },
    {
      type: "submenu",
      title: "Move to team",
      icon: "people",
      items: [
        ...teamItems,
        ...(teams.length > 0 ? [separator] : []),
        {
          title: "No team",
          checked: pixie.team_id === null,
          onSelect: () => {
            act.setTeam(null);
          },
        },
      ],
    },
    separator,
    {
      title: "Move Up",
      disabled: listed[0] === pixie.id,
      onSelect: () => {
        act.move(-1);
      },
    },
    {
      title: "Move Down",
      disabled: listed.at(-1) === pixie.id,
      onSelect: () => {
        act.move(1);
      },
    },
    separator,
    {
      title: pixie.hidden ? "Show" : "Hide",
      icon: pixie.hidden ? "eye" : "eyeSlash",
      onSelect: () => {
        act.setHidden(!pixie.hidden);
      },
    },
    separator,
    { title: "Delete…", icon: "trash", danger: true, onSelect: act.remove },
  ];
}

export interface TeamMenuActions {
  rename: () => void;
  changeHandle: () => void;
  setLeader: (pixie: string) => void;
  remove: () => void;
}

/** Rename, Change handle, Set leader, Delete team. */
export function teamMenu(section: TeamSection, act: TeamMenuActions): MenuEntry[] {
  return [
    { title: "Rename…", icon: "edit", onSelect: act.rename },
    { title: "Change handle…", icon: "at", onSelect: act.changeHandle },
    {
      type: "submenu",
      title: "Set leader",
      icon: "star",
      disabled: section.members.length === 0,
      items: section.members.map((member) => ({
        title: member.name,
        checked: section.team.leader_id === member.id,
        onSelect: () => {
          act.setLeader(member.id);
        },
      })),
    },
    separator,
    { title: "Delete team…", icon: "trash", danger: true, onSelect: act.remove },
  ];
}
