import { PixieList } from "../pixies/PixieList.tsx";
import { useShell } from "./context.ts";
import { ResizeHandle } from "./Sidebar.tsx";
import { UpdateRailDot, UpdateStrip } from "./UpdateStrip.tsx";

/** The Pixies tab's sidebar, as the Mac's PixieList: New pixie, reports, teams and pixies. */
export function PixiesSidebar() {
  const shell = useShell();
  if (shell.state.leftCollapsed) {
    return (
      <button className="dk-rail" aria-label="Open sidebar" onClick={shell.toggleSidebar}>
        <UpdateRailDot />
      </button>
    );
  }
  return (
    <aside
      className="dk-side dk-pxside"
      style={{ width: shell.desk.sidebarWidth }}
      aria-label="Pixies"
    >
      <PixieList />
      <UpdateStrip />
      <ResizeHandle />
    </aside>
  );
}
