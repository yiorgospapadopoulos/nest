import { useEffect, useState } from "react";
import { deviceStorage } from "../../store/legacyKeys.ts";
import { useBridge } from "../context.ts";
import { ISLAND_SETTINGS_KEY, loadIslandSettings } from "../islandData.ts";
import { pillRect, stripGap, type StripGap } from "../layout/pillGap.ts";

type Gap = StripGap | null;

// The tab strip's height (desktop.css --dk-tabs).
const STRIP = 40;

/**
 * Where the pill covers the strip now. The window's place comes from screenX and screenY,
 * real under X11 and XWayland (the pill's own setting); the pill sits on the primary
 * screen, taken as the one at the origin.
 */
function measure(storage: Storage): Gap {
  if (!loadIslandSettings(storage).shown) return null;
  return stripGap(
    { x: window.screenX, y: window.screenY, width: window.innerWidth, height: STRIP },
    pillRect(0, window.screen.width),
  );
}

/** The gap the tab strip leaves for the pill while it shows over the window's top. */
export function usePillGap(): Gap {
  const bridge = useBridge();
  const storage = deviceStorage();
  const [gap, setGap] = useState(() => measure(storage));
  useEffect(() => {
    const update = () => {
      setGap((current) => {
        const next = measure(storage);
        const same =
          current?.left === next?.left &&
          current?.width === next?.width &&
          current?.right === next?.right;
        return same ? current : next;
      });
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === ISLAND_SETTINGS_KEY) update();
    };
    const off = bridge.onWindowMoved(update);
    window.addEventListener("resize", update);
    window.addEventListener("storage", onStorage);
    return () => {
      off();
      window.removeEventListener("resize", update);
      window.removeEventListener("storage", onStorage);
    };
  }, [bridge, storage]);
  return gap;
}
