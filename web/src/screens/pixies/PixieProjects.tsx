import { useState } from "react";
import type { Pixie, UpdatePixieBody } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { ProjectIcon } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";

interface Props {
  pixie: Pixie;
  save: (body: UpdatePixieBody) => void;
}

/** The projects the pixie works on: every one, or a list picked from the registered repos. */
export function PixieProjects({ pixie, save }: Props) {
  const { state } = useStore();
  const [picking, setPicking] = useState(false);
  const chosen = pixie.projects;
  const close = () => {
    setPicking(false);
  };
  const choice = (label: string, body: UpdatePixieBody) => (
    <button
      key={label}
      className="asi"
      role="menuitem"
      onClick={() => {
        save(body);
        close();
      }}
    >
      {label}
    </button>
  );

  return (
    <div className="lgrp gl">
      {chosen === null && <div className="srow">All projects</div>}
      {chosen?.length === 0 && <div className="srow hint">No projects</div>}
      {chosen?.map((name) => (
        <div key={name} className="srow">
          <span className="cn">
            <ProjectIcon name={name} />
            <span>{name}</span>
          </span>
          <button
            className="pxx"
            aria-label={`Remove ${name}`}
            onClick={() => {
              save({ projects: chosen.filter((other) => other !== name) });
            }}
          >
            <Icon name="x" />
          </button>
        </div>
      ))}
      <button
        className="srow pxadd-row"
        aria-label="Add project"
        onClick={() => {
          setPicking(true);
        }}
      >
        <span className="cn">
          <Icon name="plus" />
          <span>Add project</span>
        </span>
      </button>
      {picking && (
        <ActionSheet label="Add project" title={<b>Add project</b>} onClose={close}>
          {chosen !== null && choice("All projects", { all_projects: true })}
          {state.repos
            .filter((repo) => !chosen?.includes(repo.name))
            .map((repo) => choice(repo.name, { projects: [...(chosen ?? []), repo.name] }))}
        </ActionSheet>
      )}
    </div>
  );
}
