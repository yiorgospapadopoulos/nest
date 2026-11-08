import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StoreProvider } from "../../store/StoreProvider.tsx";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { approval } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { ApprovalCard } from "./ApprovalCard.tsx";

const REASON = [
  "Uncommitted changes:",
  "  README.md",
  "Commits not on main:",
  "  1a2b3c4 Fix the login form",
  "Its branch stays.",
].join("\n");

describe("a permission card", () => {
  it("asks to remove a worktree with its work listed and no Always allow", () => {
    const storage = memoryStorage();
    render(
      <StoreProvider
        api={fakeApi()}
        connect={socketFactory().connect}
        storage={() => storage}
        location={{ protocol: "http:", host: "127.0.0.1:8765" }}
      >
        <ApprovalCard
          style="panel"
          approval={approval({
            payload: {
              tool: "worktree",
              input: { action: "remove", worktree: "/w/.claude/worktrees/nest-1a2b3c4d" },
              title: "Remove the worktree nest-1a2b3c4d? It has 1 uncommitted file.",
              reason: REASON,
              always_rule: null,
              always: false,
            },
          })}
        />
      </StoreProvider>,
    );

    expect(screen.getByText("worktree remove nest-1a2b3c4d")).toBeInTheDocument();
    const reason = screen.getByText(/Uncommitted changes/);
    expect(reason.textContent).toBe(REASON);
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Always allow/ })).not.toBeInTheDocument();
  });
});
