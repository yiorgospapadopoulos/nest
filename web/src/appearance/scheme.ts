import { useEffect, useState } from "react";
import { useAppearance } from "./context.ts";

const DARK = "(prefers-color-scheme: dark)";

function systemDarkMedia(): MediaQueryList | undefined {
  const { matchMedia } = window as { matchMedia?: Window["matchMedia"] };
  return matchMedia?.(DARK);
}

/** Nest's theme as shown now: the chosen one, or under Auto the system's, as it changes. */
export function useScheme(): "light" | "dark" {
  const { theme } = useAppearance().appearance;
  const [systemDark, setSystemDark] = useState(() => systemDarkMedia()?.matches === true);
  useEffect(() => {
    const media = systemDarkMedia();
    if (media === undefined) return;
    const update = () => {
      setSystemDark(media.matches);
    };
    media.addEventListener("change", update);
    return () => {
      media.removeEventListener("change", update);
    };
  }, []);
  if (theme !== "auto") return theme;
  return systemDark ? "dark" : "light";
}
