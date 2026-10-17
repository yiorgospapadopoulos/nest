import type { CSSProperties } from "react";
import { ACCENTS, GLASSES, THEMES, WALLPAPERS } from "../../appearance/appearance.ts";
import { useAppearance } from "../../appearance/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { Section, SegRow } from "./rows.tsx";

const title = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);

/**
 * B80 fills this in: a running chat's fireflies and a message in the accent colour. Until
 * then it shows nothing.
 */
export function AccentPreview() {
  return null;
}

/**
 * Mode and accent, then how chats look: the glass, your messages and the wallpaper, the
 * iPhone's chat background. Kept on this device.
 */
export function AppearancePage() {
  const { appearance, change } = useAppearance();
  return (
    <>
      <Section>
        <SegRow
          label="Mode"
          value={appearance.theme}
          choices={THEMES.map((theme) => ({ value: theme, label: title(theme) }))}
          onChange={(theme) => {
            change({ theme });
          }}
        />
        <div className="srow col">
          <span id="accent-label">Accent colour</span>
          <div className="swl" role="group" aria-labelledby="accent-label">
            {ACCENTS.map((accent) => (
              <button
                key={accent.id}
                className="swc"
                aria-pressed={appearance.accent === accent.id}
                aria-label={accent.label}
                title={accent.label}
                style={{ "--l": accent.light, "--d": accent.dark } as CSSProperties}
                onClick={() => {
                  change({ accent: accent.id });
                }}
              >
                <Icon name="check" />
              </button>
            ))}
          </div>
        </div>
      </Section>
      <AccentPreview />
      <Section title="Chat background">
        <div className="srow col">
          <span id="wallpaper-label">Wallpaper</span>
          <div className="wpl" role="group" aria-labelledby="wallpaper-label">
            {WALLPAPERS.map((wallpaper) => (
              <button
                key={wallpaper}
                className="wpt"
                aria-pressed={appearance.wallpaper === wallpaper}
                onClick={() => {
                  change({ wallpaper });
                }}
              >
                <i className={`wallpaper-${wallpaper}`} aria-hidden="true" />
                {title(wallpaper)}
              </button>
            ))}
          </div>
        </div>
        <div className="srow col">
          <span id="glass-label">Glass</span>
          <div className="gpl" role="group" aria-labelledby="glass-label">
            {GLASSES.map((glass) => (
              <button
                key={glass.id}
                className="wpt gpt"
                aria-pressed={appearance.glass === glass.id}
                onClick={() => {
                  change({ glass: glass.id });
                }}
              >
                {/* A small pane and control in this theme's own glass, over the wallpaper. */}
                <i
                  className={`wallpaper-${appearance.wallpaper}`}
                  data-glass={glass.id}
                  aria-hidden="true"
                >
                  <span>
                    <b />
                  </span>
                </i>
                {glass.label}
              </button>
            ))}
          </div>
        </div>
        <SegRow
          label="Your messages"
          value={appearance.bubble}
          choices={(["accent", "neutral"] as const).map((bubble) => ({
            value: bubble,
            label: title(bubble),
          }))}
          onChange={(bubble) => {
            change({ bubble });
          }}
        />
      </Section>
    </>
  );
}
