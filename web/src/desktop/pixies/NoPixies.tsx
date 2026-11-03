import { DEFAULT_COLOR, TEMPLATES } from "../../screens/pixies/templates.ts";
import { useShell } from "../shell/context.ts";
import { Button } from "../ui/controls.tsx";
import { PxGlyph } from "./glyphs.tsx";
import { Sprite } from "./Sprite.tsx";
import "./empty.css";

/** New pixie, which opens the new pixie's pane and its details to set it up. */
export function NewPixieButton({ size = "regular" }: { size?: "regular" | "large" }) {
  const shell = useShell();
  return (
    <Button
      kind="primary"
      size={size}
      className="px-es-new"
      onClick={() => {
        shell.createPixie({ name: "New pixie" }, true);
      }}
    >
      <PxGlyph name="plus" />
      New pixie
    </Button>
  );
}

/** "Create your first pixie", with New pixie and the Reviewer and Tester starters (D072). */
export function NoPixies() {
  const shell = useShell();
  return (
    <div className="px-none">
      <div className="px-none-box">
        <Sprite mascot="bluebell" color={DEFAULT_COLOR} size={64} />
        <h2>Create your first pixie</h2>
        <p>A pixie is an agent you keep: its own soul, memory and one ongoing chat.</p>
        <NewPixieButton size="large" />
        <span className="px-none-hint">Or start from a template</span>
        <div className="px-es-row">
          {TEMPLATES.map((template) => (
            <Button
              key={template.name}
              size="large"
              title={`A ${template.name.toLowerCase()} with a starter soul`}
              onClick={() => {
                shell.createPixie(
                  { name: template.name, mascot: template.mascot, soul: template.soul },
                  false,
                );
              }}
            >
              <Sprite mascot={template.mascot} color={DEFAULT_COLOR} size={14} />
              {template.name}
            </Button>
          ))}
        </div>
      </div>
    </div>
  );
}
