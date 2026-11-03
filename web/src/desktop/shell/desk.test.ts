// Regression (B117 audit, P1): new chat drafts were saved with the window's arrangement and
// came back after a restart as panes that could not be closed. The Mac never keeps them.
import { describe, expect, it } from "vitest";
import { memoryStorage } from "../../test/render.tsx";
import { ProjectState } from "../layout/project.ts";
import { EMPTY_DESK, loadDesk, saveDesk } from "./desk.ts";
import { draftPane } from "./panes.ts";

describe("the saved arrangement", () => {
  it("leaves new chat drafts out and keeps the chats", () => {
    const size = { width: 1200, height: 800 };
    const project = new ProjectState();
    project.openChat("s1", size);
    const draft = draftPane();
    project.openChat(draft, size);
    const storage = memoryStorage();
    saveDesk(storage, {
      ...EMPTY_DESK,
      tabs: { open: ["todo-ui"], current: "todo-ui", last: "todo-ui" },
      projects: { "todo-ui": project },
    });
    const restored = loadDesk(storage).projects["todo-ui"];
    expect(restored?.layout.leaves).toEqual(["s1"]);
    expect(restored?.layout.focused).toBe("s1");
    expect(restored?.selectedChat).toBe("s1");
    // The open window keeps its draft.
    expect(project.layout.leaves).toEqual(["s1", draft]);
  });
});
