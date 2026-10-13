import type { KeyboardEvent, ReactNode } from "react";
import { useAppearance } from "../../appearance/context.ts";
import { Icon } from "../../ui/Icon.tsx";

interface FrameProps {
  title: string;
  // Shown before the title, such as a pixie's sprite.
  icon?: ReactNode;
  back: string;
  onBack: () => void;
  tools?: ReactNode;
  details?: ReactNode;
  children: ReactNode;
}

/** The pushed chat screen: header with back, title and tools, over the wallpaper. */
export function Frame({ title, icon, back, onBack, tools, details, children }: FrameProps) {
  const { appearance } = useAppearance();
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") onBack();
  };
  return (
    <section className="push" aria-label={title} onKeyDown={onKeyDown}>
      <div className={`wall wallpaper-${appearance.wallpaper}`} aria-hidden="true" />
      <header className="ch-h gl">
        <div className="ch-r1">
          <button className="back" aria-label={`Back to ${back}`} onClick={onBack} autoFocus>
            <Icon name="chevl" />
            <span>{back}</span>
          </button>
          <span className="flex" />
          {tools}
        </div>
        <h2 className="ch-t">
          {icon}
          {title}
        </h2>
        {details}
      </header>
      {children}
    </section>
  );
}
