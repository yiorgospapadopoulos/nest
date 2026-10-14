import { useEffect, useMemo, useState, type ReactNode } from "react";
import { applyAppearance, loadAppearance, saveAppearance, type Appearance } from "./appearance.ts";
import { deviceStorage } from "../store/legacyKeys.ts";
import { AppearanceContext } from "./context.ts";

export function AppearanceProvider({
  storage = deviceStorage,
  children,
}: {
  storage?: () => Storage;
  children: ReactNode;
}) {
  const [appearance, setAppearance] = useState(() => loadAppearance(storage));

  useEffect(() => {
    applyAppearance(document.documentElement, appearance);
  }, [appearance]);

  const value = useMemo(
    () => ({
      appearance,
      change: (patch: Partial<Appearance>) => {
        setAppearance((current) => {
          const next = { ...current, ...patch };
          saveAppearance(storage, next);
          return next;
        });
      },
    }),
    [appearance, storage],
  );

  return (
    <AppearanceContext value={value}>
      <div className={`wall wallpaper-${appearance.wallpaper}`} aria-hidden="true" />
      {children}
    </AppearanceContext>
  );
}
