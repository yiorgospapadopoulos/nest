import type { ReactNode } from "react";
import { useStore } from "../../store/context.ts";
import { pixieList, unseenArtifacts } from "../../store/selectors.ts";
import { Icon } from "../../ui/Icon.tsx";
import { viewChoices, type ProjectView } from "../layout/project.ts";
import { useKeysText } from "../layout/useShortcuts.ts";
import { useShell } from "./context.ts";
import "./frame/frame.css";
import { openProjectTerminal } from "./frame/terminal.ts";

const TITLES: Record<ProjectView, string> = {
  workspace: "Workspace",
  board: "Board",
  artifacts: "Artifacts",
};

/**
 * The bar along the bottom of the window, as the Mac's StatusBar: in a project the
 * sidebar's squeeze triangle and Settings on the left, the Terminal button and the details
 * panel's triangle on the right; the view switch in the middle (in the Pixies tab only
 * once there is a pixie). The triangles point where their bar goes on a click.
 */
export function StatusBar() {
  const { state, actions } = useStore();
  const shell = useShell();
  const keysOf = useKeysText();
  const inProject = shell.project !== null;
  const pixies = !inProject;
  const hasViews = inProject || pixieList(state).length > 0;
  const view = shell.state.view;
  const unseen = unseenArtifacts(state, shell.project);
  const left = shell.state.leftCollapsed;
  const right = shell.state.rightCollapsed;
  return (
    <footer className="dk-status fr-status">
      {inProject && (
        <Squeeze
          title={left ? "Open sidebar" : "Squeeze sidebar"}
          keys={keysOf("toggleSidebar")}
          point={left ? "right" : "left"}
          onClick={shell.toggleSidebar}
        />
      )}
      <FooterButton
        title={`Settings (${keysOf("settings")})`}
        onClick={() => {
          shell.openSettings();
        }}
      >
        <Icon name="gear" />
        Settings
      </FooterButton>
      <span className="grow" />
      {hasViews && (
        <div className="fr-views" role="radiogroup" aria-label="View">
          {viewChoices(pixies).map((choice) => (
            <button
              key={choice}
              role="radio"
              aria-checked={view === choice}
              className={view === choice ? "fr-fbtn on" : "fr-fbtn"}
              onClick={() => {
                shell.setView(choice);
              }}
            >
              {TITLES[choice]}
              {choice === "artifacts" && unseen > 0 && (
                <span className="fr-unseen">{unseen > 99 ? "99+" : unseen}</span>
              )}
            </button>
          ))}
        </div>
      )}
      {inProject && (
        <>
          <FooterButton
            title="Open a terminal where the focused chat works"
            onClick={() => {
              openProjectTerminal(
                shell,
                { sessions: state.sessions, claudeChats: state.claudeChats, repos: state.repos },
                (text) => {
                  actions.toast(text, "error");
                },
              );
            }}
          >
            <Icon name="term" />
            Terminal
          </FooterButton>
          <Squeeze
            title={right ? "Open details" : "Squeeze details"}
            keys={keysOf("toggleActivity")}
            point={right ? "left" : "right"}
            onClick={shell.toggleActivity}
          />
        </>
      )}
    </footer>
  );
}

function FooterButton({
  title,
  onClick,
  children,
}: {
  title: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button className="fr-fbtn" title={title} onClick={onClick}>
      {children}
    </button>
  );
}

/** A side bar's squeeze button: a small triangle pointing where the bar goes. */
function Squeeze({
  title,
  keys,
  point,
  onClick,
}: {
  title: string;
  keys: string;
  point: "left" | "right";
  onClick: () => void;
}) {
  return (
    <button
      className="fr-fbtn fr-squeeze"
      title={`${title} (${keys})`}
      aria-label={title}
      onClick={onClick}
    >
      <svg viewBox="0 0 8 8" aria-hidden="true">
        <path d={point === "left" ? "M6 1L2 4l4 3z" : "M2 1l4 3-4 3z"} />
      </svg>
    </button>
  );
}
