import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { useContextMenu } from "./contextMenu.tsx";
import { Menu } from "./Menu.tsx";
import type { MenuEntry } from "./menuItems.ts";
import { closeTopOverlay } from "./overlays.ts";
import { anchored } from "./place.ts";
import { Popover } from "./Popover.tsx";
import { RenameField } from "./RenameField.tsx";

// The outside press listener starts on the next turn, after the opening press.
const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

function entries(pick: (name: string) => void): MenuEntry[] {
  return [
    { type: "section", title: "Permission mode" },
    {
      title: "Ask",
      detail: "Asks before edits",
      checked: true,
      onSelect: () => {
        pick("ask");
      },
    },
    {
      title: "Plan",
      checked: false,
      disabled: true,
      onSelect: () => {
        pick("plan");
      },
    },
    { type: "separator" },
    {
      title: "Bypass",
      checked: false,
      onSelect: () => {
        pick("bypass");
      },
    },
    {
      type: "submenu",
      title: "Runs on",
      items: [
        {
          title: "Ollama",
          onSelect: () => {
            pick("ollama");
          },
        },
      ],
    },
  ];
}

function MenuHarness({ pick }: { pick: (name: string) => void }) {
  return (
    <>
      <input aria-label="Before" />
      <Menu label="Permission mode" items={() => entries(pick)}>
        {(trigger) => <button {...trigger}>Ask</button>}
      </Menu>
      <button
        onClick={() => {
          pick("under");
        }}
      >
        Under
      </button>
    </>
  );
}

const openByPress = (name = "Ask") => {
  fireEvent.pointerDown(screen.getByRole("button", { name }), { button: 0 });
  fireEvent.pointerUp(screen.getByRole("button", { name }), { button: 0 });
};

describe("Menu", () => {
  it("opens below its button with checkmarks and runs the chosen item after closing", async () => {
    const pick = vi.fn();
    render(<MenuHarness pick={pick} />);
    openByPress();
    const menu = screen.getByRole("menu", { name: "Permission mode" });
    expect(menu).toHaveFocus();
    expect(screen.getByRole("menuitemcheckbox", { name: "Ask" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await settle();
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Bypass" }));
    expect(pick).toHaveBeenCalledWith("bypass");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("chooses the item a press moved to and released on, as AppKit's menus", () => {
    const pick = vi.fn();
    render(<MenuHarness pick={pick} />);
    fireEvent.pointerDown(screen.getByRole("button", { name: "Ask" }), {
      button: 0,
      clientX: 10,
      clientY: 10,
    });
    const bypass = screen.getByRole("menuitemcheckbox", { name: "Bypass" });
    fireEvent.pointerMove(bypass, { clientX: 12, clientY: 60 });
    fireEvent.pointerUp(bypass, { button: 0, clientX: 12, clientY: 60 });
    expect(pick).toHaveBeenCalledWith("bypass");
  });

  it("leaves a quick click's menu open, though an item came under the pointer to fit", () => {
    // The pixie's Model went from Opus to Haiku this way (wave 4).
    const pick = vi.fn();
    render(<MenuHarness pick={pick} />);
    fireEvent.pointerDown(screen.getByRole("button", { name: "Ask" }), {
      button: 0,
      clientX: 10,
      clientY: 10,
    });
    const bypass = screen.getByRole("menuitemcheckbox", { name: "Bypass" });
    fireEvent.pointerMove(bypass, { clientX: 11, clientY: 11 });
    fireEvent.pointerUp(bypass, { button: 0, clientX: 11, clientY: 11 });
    expect(pick).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("chooses on the release of a press on the item, once, with or without its click", () => {
    const pick = vi.fn();
    render(<MenuHarness pick={pick} />);
    openByPress();
    const bypass = screen.getByRole("menuitemcheckbox", { name: "Bypass" });
    fireEvent.pointerDown(bypass, { button: 0 });
    fireEvent.pointerUp(bypass, { button: 0 });
    fireEvent.click(bypass);
    expect(pick).toHaveBeenCalledTimes(1);
    expect(pick).toHaveBeenCalledWith("bypass");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("chooses an item pressed with no movement first, which WebKitGTK sends to the button", async () => {
    // Wave 7: Rewind… in a message's menu; the press went to the "…" that opened it.
    const pick = vi.fn();
    render(<MenuHarness pick={pick} />);
    openByPress();
    await settle();
    pressAt(
      screen.getByRole("menuitemcheckbox", { name: "Bypass" }),
      screen.getByRole("button", { name: "Ask" }),
    );
    expect(pick).toHaveBeenCalledTimes(1);
    expect(pick).toHaveBeenCalledWith("bypass");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("chooses on a click's press and release though something stops them and its click", () => {
    const pick = vi.fn();
    render(<MenuHarness pick={pick} />);
    openByPress();
    const stop = (event: Event) => {
      event.stopPropagation();
    };
    document.addEventListener("pointerdown", stop, true);
    document.addEventListener("pointerup", stop, true);
    try {
      const bypass = screen.getByRole("menuitemcheckbox", { name: "Bypass" });
      fireEvent.pointerDown(bypass, { button: 0 });
      fireEvent.pointerUp(bypass, { button: 0 });
    } finally {
      document.removeEventListener("pointerdown", stop, true);
      document.removeEventListener("pointerup", stop, true);
    }
    expect(pick).toHaveBeenCalledWith("bypass");
  });

  it("stays open while something under it scrolls by itself, and closes on a wheel outside", async () => {
    render(<MenuHarness pick={vi.fn()} />);
    openByPress();
    await settle();
    fireEvent.scroll(screen.getByRole("button", { name: "Under" }));
    fireEvent(window, new Event("resize"));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.wheel(screen.getByRole("button", { name: "Under" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("takes its button's tooltip off while open, so no tooltip covers its first items", () => {
    render(
      <Menu label="Actions" items={() => entries(vi.fn())}>
        {(trigger) => (
          <button {...trigger} title="Edit, rewind or fork">
            More
          </button>
        )}
      </Menu>,
    );
    const button = screen.getByRole("button", { name: "More" });
    fireEvent.pointerDown(button, { button: 0 });
    expect(button).not.toHaveAttribute("title");
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(button).toHaveAttribute("title", "Edit, rewind or fork");
  });

  it("moves with the arrows past titles, separators and disabled items, and Enter chooses", () => {
    const pick = vi.fn();
    render(<MenuHarness pick={pick} />);
    const button = screen.getByRole("button", { name: "Ask" });
    button.focus();
    fireEvent.keyDown(button, { key: "ArrowDown" });
    const menu = screen.getByRole("menu");
    const active = () => document.getElementById(menu.getAttribute("aria-activedescendant") ?? "");
    expect(active()).toHaveAccessibleName("Ask");
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(active()).toHaveAccessibleName("Bypass");
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(active()).toHaveAccessibleName("Ask");
    fireEvent.keyDown(menu, { key: "r" });
    expect(active()).toHaveAccessibleName("Runs on");
    fireEvent.keyDown(menu, { key: "ArrowRight" });
    const sub = screen.getByRole("menu", { name: "Runs on" });
    expect(sub).toHaveFocus();
    fireEvent.keyDown(sub, { key: "ArrowLeft" });
    expect(screen.queryByRole("menu", { name: "Runs on" })).not.toBeInTheDocument();
    fireEvent.keyDown(menu, { key: "ArrowRight" });
    fireEvent.keyDown(screen.getByRole("menu", { name: "Runs on" }), { key: "Enter" });
    expect(pick).toHaveBeenCalledWith("ollama");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });

  it("closes on Escape without the window seeing it, and gives the focus back", () => {
    const onWindow = vi.fn();
    window.addEventListener("keydown", onWindow);
    render(<MenuHarness pick={vi.fn()} />);
    screen.getByRole("textbox", { name: "Before" }).focus();
    openByPress();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    window.removeEventListener("keydown", onWindow);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(onWindow).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Before" })).toHaveFocus();
  });

  it("closes on a press outside, which does nothing else", async () => {
    const pick = vi.fn();
    render(<MenuHarness pick={pick} />);
    openByPress();
    await settle();
    const under = screen.getByRole("button", { name: "Under" });
    fireEvent.pointerDown(under, { button: 0 });
    fireEvent.click(under);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(pick).not.toHaveBeenCalled();
    // The next click is the user's own again.
    fireEvent.pointerDown(under, { button: 0 });
    fireEvent.click(under);
    expect(pick).toHaveBeenCalledWith("under");
  });

  it("closes from the window's Ctrl+W order, and its button toggles it", async () => {
    render(<MenuHarness pick={vi.fn()} />);
    openByPress();
    act(() => {
      expect(closeTopOverlay()).toBe(true);
    });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(closeTopOverlay()).toBe(false);
    openByPress();
    await settle();
    openByPress();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});

function RowWithMenu({ pick }: { pick: (name: string) => void }) {
  const { onContextMenu, menu } = useContextMenu("Chat", () => [
    {
      title: "Rename",
      onSelect: () => {
        pick("rename");
      },
    },
  ]);
  return (
    <>
      <button onContextMenu={onContextMenu}>Row</button>
      {menu}
    </>
  );
}

describe("Context menu", () => {
  it("opens at the pointer on a right click and chooses", () => {
    const pick = vi.fn();
    render(<RowWithMenu pick={pick} />);
    fireEvent.contextMenu(screen.getByRole("button", { name: "Row" }), {
      clientX: 40,
      clientY: 30,
      button: 2,
    });
    expect(screen.getByRole("menu", { name: "Chat" })).toHaveFocus();
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    expect(pick).toHaveBeenCalledWith("rename");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});

function PopoverHarness({ onUnder, onDetails }: { onUnder: () => void; onDetails?: () => void }) {
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        ref={anchor}
        onClick={() => {
          setOpen(!open);
        }}
      >
        Usage
      </button>
      {open && (
        <Popover
          anchor={anchor}
          label="Usage"
          onClose={() => {
            setOpen(false);
          }}
        >
          <button onClick={onDetails}>Details</button>
        </Popover>
      )}
      <button onClick={onUnder}>Under</button>
    </>
  );
}

describe("Popover", () => {
  it("focuses its first control and closes on Escape and on a press outside", async () => {
    const under = vi.fn();
    render(<PopoverHarness onUnder={under} />);
    screen.getByRole("button", { name: "Usage" }).focus();
    fireEvent.click(screen.getByRole("button", { name: "Usage" }));
    expect(screen.getByRole("button", { name: "Details" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("dialog", { name: "Usage" }), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Usage" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Usage" }));
    await settle();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Under" }));
    fireEvent.click(screen.getByRole("button", { name: "Under" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // Unlike a menu, the press still reaches what it pressed.
    expect(under).toHaveBeenCalled();
  });

  it("clicks a row pressed with no movement first, which WebKitGTK sends to the button", () => {
    // Wave 7: General in the + popover; the press went to the +, which closed it.
    const details = vi.fn();
    render(<PopoverHarness onUnder={vi.fn()} onDetails={details} />);
    const usage = screen.getByRole("button", { name: "Usage" });
    fireEvent.click(usage);
    const row = screen.getByRole("button", { name: "Details" });
    pressAt(row, usage);
    expect(details).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("dialog", { name: "Usage" })).toBeInTheDocument();
  });
});

/**
 * A press and release on `under` with no movement before them, as WebKitGTK sends them: to
 * `sent`, the element the pointer was last over, then its click there too.
 */
function pressAt(under: Element, sent: Element) {
  const before = Object.getOwnPropertyDescriptor(document, "elementFromPoint");
  Object.defineProperty(document, "elementFromPoint", {
    configurable: true,
    value: () => under,
  });
  try {
    fireEvent.pointerDown(sent, { button: 0 });
    fireEvent.pointerUp(sent, { button: 0 });
    fireEvent.click(sent, { button: 0, detail: 1 });
  } finally {
    if (before === undefined) Reflect.deleteProperty(document, "elementFromPoint");
    else Object.defineProperty(document, "elementFromPoint", before);
  }
}

describe("RenameField", () => {
  const renderField = () => {
    const commit = vi.fn();
    const cancel = vi.fn();
    const view = render(
      <RenameField value="Old name" label="Chat name" onCommit={commit} onCancel={cancel} />,
    );
    return { field: screen.getByRole("textbox", { name: "Chat name" }), commit, cancel, view };
  };

  it("opens selected and saves the trimmed name on Enter, once", () => {
    const { field, commit, cancel } = renderField();
    expect(field).toHaveFocus();
    expect((field as HTMLInputElement).selectionEnd).toBe("Old name".length);
    fireEvent.change(field, { target: { value: "  New name " } });
    fireEvent.keyDown(field, { key: "Enter" });
    fireEvent.blur(field);
    expect(commit).toHaveBeenCalledTimes(1);
    expect(commit).toHaveBeenCalledWith("New name");
    expect(cancel).not.toHaveBeenCalled();
  });

  it("keeps the old name on Escape, which goes no further", () => {
    const onWindow = vi.fn();
    window.addEventListener("keydown", onWindow);
    const { field, commit, cancel } = renderField();
    fireEvent.change(field, { target: { value: "Other" } });
    fireEvent.keyDown(field, { key: "Escape" });
    window.removeEventListener("keydown", onWindow);
    expect(cancel).toHaveBeenCalled();
    expect(commit).not.toHaveBeenCalled();
    expect(onWindow).not.toHaveBeenCalled();
  });

  it("saves on blur, and saves nothing for an empty or unchanged name", () => {
    const first = renderField();
    fireEvent.change(first.field, { target: { value: "Blurred" } });
    fireEvent.blur(first.field);
    expect(first.commit).toHaveBeenCalledWith("Blurred");
    first.view.unmount();
    const second = renderField();
    fireEvent.change(second.field, { target: { value: "   " } });
    fireEvent.keyDown(second.field, { key: "Enter" });
    expect(second.commit).not.toHaveBeenCalled();
    expect(second.cancel).toHaveBeenCalled();
  });
});

describe("Placement", () => {
  it("opens above when there is no room below, and stays inside the window", () => {
    const view = { width: 800, height: 600 };
    const size = { width: 200, height: 150 };
    expect(anchored({ left: 100, top: 100, width: 60, height: 22 }, size, view)).toEqual({
      left: 100,
      top: 126,
    });
    expect(anchored({ left: 700, top: 540, width: 60, height: 22 }, size, view)).toEqual({
      left: 594,
      top: 386,
    });
  });
});
