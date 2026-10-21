import type { KeyboardEvent, ReactNode } from "react";
import type { ChatStatus } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";

interface FrameProps {
  title: string;
  // Shown before the title, such as a pixie's sprite.
  icon?: ReactNode;
  // A dot in the status color right after the title, named by the status word; `plain`
  // keeps the run tone a dot where nothing works in Nest (B80).
  status?: ChatStatus & { plain?: boolean };
  // Where Back goes, named only to assistive technology.
  back: string;
  onBack: () => void;
  // At the bar's end, such as the chat's menu.
  tools?: ReactNode;
  // A line under the bar, such as a pixie's tabs.
  details?: ReactNode;
  children: ReactNode;
}

/**
 * The pushed chat screen under a flat bar, as the Mac's pane header (B102): a back chevron,
 * the name on one line with its status dot, then the tools.
 */
export function Frame({ title, icon, status, back, onBack, tools, details, children }: FrameProps) {
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") onBack();
  };
  return (
    <section className="push" aria-label={title} onKeyDown={onKeyDown}>
      <header className="ch-h">
        <div className="ch-r1">
          <button className="back" aria-label={`Back to ${back}`} onClick={onBack} autoFocus>
            <Icon name="chevl" />
          </button>
          <div className="ch-t">
            <h2>
              {icon}
              {title}
            </h2>
            {status !== undefined && (
              <Dot tone={status.tone} label={status.label} plain={status.plain === true} />
            )}
          </div>
          {tools}
        </div>
        {details}
      </header>
      {children}
    </section>
  );
}
