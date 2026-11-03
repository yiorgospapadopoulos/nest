// Settings > Keyboard shortcuts records keys pressed anywhere in the window, before the
// window's own shortcuts see them, and says on the row why keys were refused.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { memoryStorage } from "../../../test/render.tsx";
import { ShortcutsStore } from "../../layout/shortcuts.ts";
import { ShortcutsPage } from "./ShortcutsPage.tsx";

describe("the shortcuts recorder", () => {
  it("takes the next keys for the command, refuses another's, and Escape cancels", () => {
    const store = new ShortcutsStore(memoryStorage());
    const window = vi.fn();
    globalThis.addEventListener("keydown", window);
    render(<ShortcutsPage store={store} />);
    fireEvent.click(screen.getByRole("button", { name: "Change New chat" }));
    expect(screen.getByText("Press keys")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "k", code: "KeyK", ctrlKey: true });
    expect(screen.getByText("Ctrl+K is already Search chats and commands")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "J", code: "KeyJ", ctrlKey: true, shiftKey: true });
    expect(store.shortcut("newChat")).toMatchObject({ key: "j", ctrl: true, shift: true });
    expect(screen.queryByText("Press keys")).toBeNull();
    expect(screen.getByText("Ctrl+Shift+J")).toBeInTheDocument();
    // The window's shortcuts never saw the recorded keys.
    expect(window).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Change Settings" }));
    fireEvent.keyDown(document.body, { key: "Escape", code: "Escape" });
    expect(screen.queryByText("Press keys")).toBeNull();
    expect(store.isDefault("settings")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Restore defaults" }));
    expect(store.hasChanges).toBe(false);
    expect(screen.getByRole("button", { name: "Restore defaults" })).toBeDisabled();
    globalThis.removeEventListener("keydown", window);
  });
});
