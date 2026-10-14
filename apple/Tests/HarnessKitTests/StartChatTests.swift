import CoreGraphics
import Foundation
import Testing

@testable import HarnessKit

private let workspace = CGSize(width: 1000, height: 600)
/// 2026-10-06 12:00 UTC.
private let noon = Date(timeIntervalSince1970: 1_791_288_000)

/// B39: the empty workspace's composer, the bottom bar's Terminal button and the usage
/// chip at the top right.
@Suite struct StartChatTests {
    @Test func aDraftPaneBecomesTheChat() {
        var state = ProjectState()
        state.openChat("c1", in: workspace)
        state.openChat("draft-1", in: workspace)

        state.startChat(fromDraft: "draft-1", as: "s1", in: workspace)

        #expect(state.layout.leaves == ["c1", "s1"])
        #expect(state.selectedChat == "s1")
    }

    /// The empty workspace's composer has no pane: its chat opens in one.
    @Test func aDraftWithoutAPaneOpensTheChat() {
        var state = ProjectState()
        state.view = .board

        state.startChat(fromDraft: "draft-start-todo-ui", as: "s1", in: workspace)

        #expect(state.layout.leaves == ["s1"])
        #expect(state.layout.focused == "s1")
        #expect(state.selectedChat == "s1")
        #expect(state.view == .workspace)
    }
}

@Suite struct ProjectTerminalTests {
    @Test func withNoTerminalANewOneOpensInTheProjectFolder() {
        var state = ProjectState()
        state.openChat("c1", in: workspace)
        state.openTool(.browser(), in: workspace)

        let result = state.projectTerminal(folder: "/repo/", in: workspace)

        #expect(result.opened)
        #expect(result.pane.kind == .terminal)
        #expect(result.pane.folder == "/repo")
        #expect(state.layout.focused == result.pane.id)
        #expect(state.openTools.filter { $0.kind == .terminal } == [result.pane])
    }

    /// Any of the project's terminals counts, whatever folder it runs in, such as a
    /// chat's worktree.
    @Test func anOpenTerminalIsFocusedInstead() {
        var state = ProjectState()
        let worktree = state.terminal(for: "/repo/.worktrees/a", in: workspace).pane
        state.openChat("c1", in: workspace)
        state.view = .board

        let result = state.projectTerminal(folder: "/repo", in: workspace)

        #expect(!result.opened)
        #expect(result.pane == worktree)
        #expect(state.layout.focused == worktree.id)
        #expect(state.view == .workspace)
        #expect(state.openTools == [worktree])
    }
}

@MainActor
@Suite struct UsageChipTests {
    func window(_ used: Double, resetsIn minutes: Double?) -> LimitWindow {
        LimitWindow(
            utilization: used, resetsAt: minutes.map { noon.addingTimeInterval($0 * 60) },
            updatedAt: nil)
    }

    @Test func durationsFloorToWholeUnits() {
        #expect(UsageChip.duration(0) == "now")
        #expect(UsageChip.duration(-30) == "now")
        #expect(UsageChip.duration(59) == "0m")
        #expect(UsageChip.duration(45 * 60 + 59) == "45m")
        #expect(UsageChip.duration(2 * 3600) == "2h")
        #expect(UsageChip.duration(2 * 3600 + 5 * 60 + 30) == "2h 5m")
        #expect(UsageChip.duration(3 * 86400) == "3d")
        #expect(UsageChip.duration(3 * 86400 + 4 * 3600 + 59 * 60) == "3d 4h")
    }

    @Test func barTonesByUsedPercent() {
        #expect(UsageChip.tone(used: 0.79) == .neutral)
        #expect(UsageChip.tone(used: 0.80) == .amber)
        #expect(UsageChip.tone(used: 0.899) == .amber)
        #expect(UsageChip.tone(used: 0.90) == .red)
        #expect(UsageChip.tone(used: 1.2) == .red)
    }

    @Test func bothWindowsWithTheirResets() throws {
        let limits = UsageLimits(
            fiveHour: window(0.304, resetsIn: 125), sevenDay: window(0.06, resetsIn: 4560))

        let chip = try #require(UsageChip.of(limits, now: noon))

        #expect(chip.entries.map(\.text) == ["30% 2h 5m", "6% 3d 4h"])
        #expect(
            chip.tooltip == "30% used · Resets in 2h 5m · 6% used · Resets in 3d 4h")
        #expect(chip.used == 0.304)
        #expect(chip.tone == .neutral)
    }

    /// The bar follows the tightest window; a window without a reset time shows its size.
    @Test func theTightestWindowFillsTheBar() throws {
        let limits = UsageLimits(
            fiveHour: window(0.4, resetsIn: nil), sevenDay: window(0.92, resetsIn: -1))

        let chip = try #require(UsageChip.of(limits, now: noon))

        #expect(chip.entries.map(\.text) == ["40% 5h", "92% now"])
        #expect(chip.tooltip == "40% used · 5h window · 92% used · Resets now")
        #expect(chip.used == 0.92)
        #expect(chip.tone == .red)
    }

    @Test func percentagesAreClamped() throws {
        let chip = try #require(
            UsageChip.of(
                UsageLimits(fiveHour: nil, sevenDay: window(1.5, resetsIn: nil)), now: noon))
        #expect(chip.entries.map(\.text) == ["100% wk"])
        #expect(chip.used == 1)
        let empty = try #require(
            UsageChip.of(
                UsageLimits(fiveHour: window(-0.1, resetsIn: nil), sevenDay: nil), now: noon))
        #expect(empty.entries.map(\.text) == ["0% 5h"])
        #expect(empty.used == 0)
    }

    @Test func nothingReportedShowsNoChip() {
        #expect(UsageChip.of(nil, now: noon) == nil)
        #expect(UsageChip.of(UsageLimits(fiveHour: nil, sevenDay: nil), now: noon) == nil)
    }
}

@MainActor
@Suite struct PreparedDraftTests {
    final class Draft {
        var model: String?
    }

    /// The empty workspace's draft takes the new-chat defaults once, when it is made.
    @Test func aNewDraftIsPreparedOnce() {
        let book = DraftBook { Draft() }
        var prepared = 0
        let draft = book.draft(for: "draft-start-a") {
            prepared += 1
            $0.model = "opus"
        }
        draft.model = "sonnet"
        let again = book.draft(for: "draft-start-a") { $0.model = "haiku" }

        #expect(again === draft)
        #expect(again.model == "sonnet")
        #expect(prepared == 1)
    }
}
