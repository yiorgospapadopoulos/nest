import { use, type KeyboardEvent, type ReactNode } from "react";
import type { ChatStatus } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { FrameChrome } from "./frameChrome.ts";

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
  // A line under the name, such as where the chat works and its dev server's ports (B108).
  subtitle?: ReactNode;
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
export function Frame({
  title,
  icon,
  status,
  back,
  onBack,
  subtitle,
  tools,
  details,
  children,
}: FrameProps) {
  const chrome = use(FrameChrome);
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape" && chrome === null) onBack();
  };
  const name = (
    <>
      <h2>
        {icon}
        {title}
      </h2>
      {status !== undefined && (
        <Dot tone={status.tone} label={status.label} plain={status.plain === true} />
      )}
    </>
  );
  return (
    <section className="push" aria-label={title} onKeyDown={onKeyDown}>
      <header className="ch-h">
        <div className="ch-r1">
          {chrome === null ? (
            <button className="back" aria-label={`Back to ${back}`} onClick={onBack} autoFocus>
              <Icon name="chevl" />
            </button>
          ) : (
            chrome.lead
          )}
          <div className="ch-t">
            {subtitle === undefined ? (
              name
            ) : (
              <div className="ch-tc">
                <div className="ch-tn">{name}</div>
                <div className="ch-st">{subtitle}</div>
              </div>
            )}
          </div>
          {tools}
          {chrome?.trail}
        </div>
        {details}
      </header>
      {children}
    </section>
  );
}
