import { useId, useState } from "react";
import type { Pixie, PixieSkill, UpdatePixieBody } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { Sheet } from "../../ui/Sheet.tsx";
import { AddHeading } from "./AddHeading.tsx";
import { usePending } from "./pending.ts";

interface Props {
  pixie: Pixie;
  save: (body: UpdatePixieBody) => Promise<unknown>;
}

/**
 * The skills the pixie may use, as removable chips; none chosen means every skill. Add
 * offers the skills not chosen yet, standalone and from plugins, in a sheet that scrolls
 * (B85). A quick second change builds
 * on the first, not on the list the Mac has not answered for yet.
 */
export function PixieSkills({ pixie, save }: Props) {
  const { actions } = useStore();
  const [skills, setSkills] = usePending(pixie.skills, (next) => save({ skills: next }));
  // Open from Add: null while the skills load.
  const [sheet, setSheet] = useState<{ offered: PixieSkill[] | null } | null>(null);
  const open = async () => {
    setSheet({ offered: null });
    const found = await actions.pixieSkills();
    setSheet(found === null ? null : { offered: found });
  };
  const close = () => {
    setSheet(null);
  };

  return (
    <>
      <AddHeading title="Skills" label="Add skill" popup onAdd={() => void open()} />
      <div className="lgrp gl pad">
        <div className="pxchips">
          {skills.length === 0 && <span className="hint">All skills</span>}
          {skills.map((name) => (
            <span key={name} className="pxchip">
              <code>{name}</code>
              <button
                aria-label={`Remove ${name}`}
                onClick={() => {
                  setSkills(skills.filter((other) => other !== name));
                }}
              >
                <Icon name="x" />
              </button>
            </span>
          ))}
        </div>
      </div>
      {sheet !== null && (
        <Sheet title="Add skill" onClose={close}>
          {sheet.offered === null ? (
            <p className="hint">Loading skills</p>
          ) : (
            <SkillList
              offered={sheet.offered}
              chosen={skills}
              onPick={(name) => {
                setSkills([...skills, name]);
                close();
              }}
            />
          )}
        </Sheet>
      )}
    </>
  );
}

interface ListProps {
  offered: PixieSkill[];
  chosen: string[];
  onPick: (name: string) => void;
}

// The group of skills that come from no plugin.
const OWN = "Your skills";

/**
 * The skills not chosen yet, those of no plugin first and then each plugin's, a plugin's
 * named without its "plugin:" prefix; a search narrows them by name and description.
 */
function SkillList({ offered, chosen, onPick }: ListProps) {
  const [query, setQuery] = useState("");
  const left = offered.filter((skill) => !chosen.includes(skill.name));
  const words = query.trim().toLowerCase();
  const shown = left.filter((skill) =>
    `${skill.name}\n${skill.description ?? ""}`.toLowerCase().includes(words),
  );
  const plugins = [...new Set(shown.flatMap(({ plugin }) => (plugin === null ? [] : [plugin])))];
  const groups: [string, PixieSkill[]][] = [
    [OWN, shown.filter(({ plugin }) => plugin === null)],
    ...plugins
      .sort()
      .map((name): [string, PixieSkill[]] => [name, shown.filter(({ plugin }) => plugin === name)]),
  ];
  if (offered.length === 0) return <p className="hint">No skills installed</p>;
  if (left.length === 0) return <p className="hint">Every skill is chosen</p>;
  return (
    <>
      <input
        className="pxin pxin-sm pxsearch"
        type="search"
        aria-label="Search skills"
        placeholder="Search skills"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
      />
      {shown.length === 0 && <p className="hint">No matching skills</p>}
      <div className="pxskills">
        {groups.map(
          ([group, members]) =>
            members.length > 0 && (
              <SkillGroup key={group} title={group} skills={members} onPick={onPick} />
            ),
        )}
      </div>
    </>
  );
}

function SkillGroup({
  title,
  skills,
  onPick,
}: {
  title: string;
  skills: PixieSkill[];
  onPick: (name: string) => void;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id}>
      <h3 id={id} className="pxsub">
        {title}
      </h3>
      <div className="lgrp gl">
        {skills.map((skill) => (
          <button
            key={skill.name}
            className="pxrow-d"
            onClick={() => {
              onPick(skill.name);
            }}
          >
            <span className="pxdt">
              <b>{shortName(skill)}</b>
              {skill.description !== null && <span>{skill.description}</span>}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

/** A plugin's skill without its "plugin:" prefix. */
function shortName(skill: PixieSkill): string {
  const { name, plugin } = skill;
  return plugin !== null && name.startsWith(`${plugin}:`) ? name.slice(plugin.length + 1) : name;
}
