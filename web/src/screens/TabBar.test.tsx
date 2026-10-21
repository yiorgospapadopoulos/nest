import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TabBar } from "./TabBar.tsx";

describe("the tab bar (B102)", () => {
  it("names the tabs as the Mac does, Needs you first", () => {
    render(<TabBar tab="projects" onTab={vi.fn()} badge={0} />);
    const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabs).toEqual(["Needs you", "Chats", "Settings"]);
    expect(screen.getByRole("tab", { name: "Chats" })).toHaveAttribute("aria-selected", "true");
    // The ids and their views stay as before.
    expect(screen.getByRole("tab", { name: "Needs you" })).toHaveAttribute(
      "aria-controls",
      "view-inbox",
    );
    expect(screen.getByRole("tab", { name: "Chats" })).toHaveAttribute(
      "aria-controls",
      "view-projects",
    );
  });

  it("shows what needs the user as a quiet number after the label, not a badge", () => {
    const { container } = render(<TabBar tab="inbox" onTab={vi.fn()} badge={6} />);
    const tab = screen.getByRole("tab", { name: "Needs you 6" });
    const count = tab.querySelector(".cnt");
    expect(count).toHaveTextContent("6");
    expect(container.querySelector(".badge")).toBeNull();
  });

  it("shows no number while nothing needs the user", () => {
    const { container } = render(<TabBar tab="inbox" onTab={vi.fn()} badge={0} />);
    expect(container.querySelector(".cnt")).toBeNull();
  });

  it("is a flat bar, not a raised panel", () => {
    render(<TabBar tab="inbox" onTab={vi.fn()} badge={0} />);
    expect(screen.getByRole("tablist", { name: "Sections" })).not.toHaveClass("gl");
  });
});
