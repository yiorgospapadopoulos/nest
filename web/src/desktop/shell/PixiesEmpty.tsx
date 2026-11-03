import { NewPixieButton } from "../pixies/NoPixies.tsx";
import { PxGlyph } from "../pixies/glyphs.tsx";
import { listedPixies } from "../pixies/order.ts";
import { Sprite, WorkingDot } from "../pixies/Sprite.tsx";
import { useStore } from "../../store/context.ts";
import { pixieWorking } from "../../store/selectors.ts";
import { Button } from "../ui/controls.tsx";
import { useShell } from "./context.ts";

// The pixies offered here; the list holds the rest (PixiesView.swift).
const OFFERED = 4;

/**
 * The Pixies tab's empty workspace, as the Mac's NoPixiePanes: the listed pixies to open
 * and New pixie, or, while every pixie is hidden, a way to list them again.
 */
export function PixiesEmpty() {
  const { state } = useStore();
  const shell = useShell();
  const listed = listedPixies(state.pixies, shell.showsHiddenPixies);

  if (listed.length === 0) {
    return (
      <div className="px-panes-empty">
        <PxGlyph name="eyeSlash" className="px-es-icon small" />
        <h3>All pixies are hidden</h3>
        <div className="px-es-row">
          <Button
            onClick={() => {
              shell.setShowsHiddenPixies(true);
            }}
          >
            Show hidden
          </Button>
          <NewPixieButton />
        </div>
      </div>
    );
  }

  return (
    <div className="px-panes-empty">
      <PxGlyph name="workspace" className="px-es-icon" />
      <p>Open a pixie, or drag pixies here to chat with them side by side</p>
      <div className="px-es-row">
        {listed.slice(0, OFFERED).map((pixie) => {
          const working = pixieWorking(state, pixie);
          return (
            <Button
              key={pixie.id}
              size="large"
              title={`Open ${pixie.name}`}
              onClick={() => {
                shell.openPixie(pixie.id);
              }}
            >
              <Sprite
                mascot={pixie.mascot}
                color={pixie.color}
                size={14}
                working={working}
                phaseKey={pixie.id}
              />
              {pixie.name}
              <WorkingDot working={working} />
            </Button>
          );
        })}
      </div>
      <NewPixieButton />
    </div>
  );
}
