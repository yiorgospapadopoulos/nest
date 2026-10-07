import type { CSSProperties } from "react";
import { ACCENTS, THEMES, WALLPAPERS } from "../../appearance/appearance.ts";
import { useAppearance } from "../../appearance/context.ts";
import { Icon } from "../../ui/Icon.tsx";

const title = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);

/** Theme, accent, message bubble and wallpaper, kept on this device. */
export function AppearanceCard() {
  const { appearance, change } = useAppearance();
  return (
    <section aria-labelledby="appearance-title">
      <h2 className="pg-h" id="appearance-title">
        Appearance
      </h2>
      <div className="lgrp gl">
        <div className="srow">
          <span id="theme-label">Theme</span>
          <div className="mseg" role="group" aria-labelledby="theme-label">
            {THEMES.map((theme) => (
              <button
                key={theme}
                aria-pressed={appearance.theme === theme}
                onClick={() => {
                  change({ theme });
                }}
              >
                {title(theme)}
              </button>
            ))}
          </div>
        </div>
        <div className="srow col">
          <span id="accent-label">Accent</span>
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
        <div className="srow">
          <span id="bubble-label">Your messages</span>
          <div className="mseg" role="group" aria-labelledby="bubble-label">
            {(["accent", "neutral"] as const).map((bubble) => (
              <button
                key={bubble}
                aria-pressed={appearance.bubble === bubble}
                onClick={() => {
                  change({ bubble });
                }}
              >
                {title(bubble)}
              </button>
            ))}
          </div>
        </div>
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
      </div>
    </section>
  );
}
