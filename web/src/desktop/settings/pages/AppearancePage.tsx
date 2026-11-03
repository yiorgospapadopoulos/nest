import { useState, type CSSProperties } from "react";
import { ACCENTS, type Appearance } from "../../../appearance/appearance.ts";
import { useAppearance } from "../../../appearance/context.ts";
import { deviceStorage } from "../../../store/legacyKeys.ts";
import {
  ISLAND_SETTINGS_KEY,
  loadIslandSettings,
  saveIslandSettings,
  type IslandSettings,
} from "../../islandData.ts";
import { Segmented } from "../../ui/controls.tsx";
import { SettingsRow, SettingsSection, SwitchRow } from "../rows.tsx";
import "../parts1/parts1.css";

const MODES: { value: Appearance["theme"]; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

/** The Mac's Appearance (GeneralPages.swift): mode and accent, then the pill's Island settings. */
export function AppearancePage() {
  const { appearance, change } = useAppearance();
  return (
    <>
      <SettingsSection>
        <SettingsRow label="Mode">
          <Segmented
            label="Mode"
            value={appearance.theme}
            options={MODES}
            onChange={(theme) => {
              change({ theme });
            }}
          />
        </SettingsRow>
        <SettingsRow label="Accent colour">
          <span className="dks-swatches" role="radiogroup" aria-label="Accent colour">
            {ACCENTS.map((accent) => (
              <button
                key={accent.id}
                type="button"
                role="radio"
                className="dks-swatch"
                aria-checked={appearance.accent === accent.id}
                aria-label={accent.label}
                title={accent.label}
                style={{ "--l": accent.light, "--d": accent.dark } as CSSProperties}
                onClick={() => {
                  change({ accent: accent.id });
                }}
              >
                <i />
              </button>
            ))}
          </span>
        </SettingsRow>
      </SettingsSection>
      <IslandSection />
    </>
  );
}

/** The pixie pill's settings, kept on this device, as the Mac's Island settings (B114). */
function IslandSection() {
  const storage = deviceStorage();
  const [settings, setSettings] = useState<IslandSettings>(() => loadIslandSettings(storage));
  const change = (patch: Partial<IslandSettings>) => {
    const next = { ...settings, ...patch };
    saveIslandSettings(storage, next);
    setSettings(next);
    // The pill window hears the change as a storage event; this window's strip gap needs one too.
    window.dispatchEvent(new StorageEvent("storage", { key: ISLAND_SETTINGS_KEY }));
  };
  return (
    <SettingsSection title="Island settings">
      <SwitchRow
        label="Show the island"
        on={settings.shown}
        onChange={(shown) => {
          change({ shown });
        }}
      />
      <SettingsRow label="Order">
        <Segmented
          label="Order"
          value={settings.order}
          options={[
            { value: "newest", label: "Newest first" },
            { value: "oldest", label: "Oldest first" },
          ]}
          onChange={(order) => {
            change({ order });
          }}
        />
      </SettingsRow>
    </SettingsSection>
  );
}
