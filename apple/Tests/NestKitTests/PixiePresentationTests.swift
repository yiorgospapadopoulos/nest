import Foundation
import Testing

@testable import NestKit

@Suite struct PixiePresentationTests {
    @Test func aPixieChatsRepoNamesItsPixie() {
        #expect(Pixie.id(ofRepo: "pixie:reviewer") == "reviewer")
        #expect(Pixie.id(ofRepo: "pixie:") == nil)
        #expect(Pixie.id(ofRepo: "cv-page") == nil)
    }

    /// A model change the daemon answered by leaving Auto gets a notice; nothing else does.
    @Test func droppingOutOfAutoIsToldOnlyForAModelChange() throws {
        var auto = Fixture.decode(Pixie.self, "pixie")
        auto.permissionMode = .auto
        var asking = auto
        asking.permissionMode = .default
        #expect(auto.droppedAuto(by: UpdatePixieRequest(model: "haiku"), saved: asking))
        #expect(
            auto.droppedAuto(
                by: UpdatePixieRequest(provider: "codex", model: "gpt-5.5-mini"), saved: asking))
        // Still Auto, not in Auto before, a mode picked too, or no model change.
        #expect(!auto.droppedAuto(by: UpdatePixieRequest(model: "opus"), saved: auto))
        #expect(!asking.droppedAuto(by: UpdatePixieRequest(model: "haiku"), saved: asking))
        #expect(
            !auto.droppedAuto(
                by: UpdatePixieRequest(model: "haiku", permissionMode: .plan), saved: asking))
        #expect(!auto.droppedAuto(by: UpdatePixieRequest(name: "N"), saved: asking))
    }

    @Test func choicesLeaveUnknownOut() {
        // In the order of design/mascots.toml (B89).
        #expect(
            Mascot.choices.map(\.rawValue) == [
                "bluebell", "dragonfly", "moth", "firefly", "rose", "frost", "sprig",
                "nightshade", "brook", "star",
            ])
        #expect(Mascot.choices.allSatisfy { $0.rows.count == 14 })
        #expect(Mascot.choices.allSatisfy { $0.rows.allSatisfy { $0.count == 14 } })
        #expect(Mascot.unknown.rows.isEmpty)
        #expect(ProjectAccess.choices.map(\.label) == ["Edit", "Read only", "None"])
        #expect(ProjectAccess.noAccess.rawValue == "none")
        #expect(
            ProjectAccess.allCases.map(\.summary) == [
                "Reads and edits its projects like any chat",
                "Reads its projects, writes only in its own folder", "Works only in its own folder",
                "",
            ])
        #expect(ProjectAccess.unknown.label == "Unknown")
        #expect(Autonomy.choices.map(\.label) == ["Observe", "Message", "Start", "Answer"])
        #expect(Autonomy.unknown.label == "Unknown")
        #expect(
            Autonomy.allCases.map(\.summary) == [
                "Reads chats in its projects.",
                "Also writes to them, nudges or stops them.",
                "Also starts chats in their own worktree.",
                "Also answers approvals, questions and plans in chats it started.", "",
            ])
    }

    @Test func coloursReadAndWriteHex() throws {
        let rgba = try #require(PixieColor.rgba("#8B7CF6"))
        #expect(rgba == RGBA(red: 139 / 255, green: 124 / 255, blue: 246 / 255, alpha: 1))
        #expect(PixieColor.rgba("8B7CF6") == nil)
        #expect(PixieColor.rgba("#8B7CF") == nil)
        #expect(PixieColor.rgba("#GGGGGG") == nil)
        #expect(PixieColor.hex(red: rgba.red, green: rgba.green, blue: rgba.blue) == "#8B7CF6")
        #expect(PixieColor.hex(red: 2, green: -1, blue: 0.5) == "#FF0080")
        #expect(!PixieColor.isCustom("#8b7cf6"))
        #expect(PixieColor.isCustom("#123456"))
        #expect(PixieColor.standard == "#8B7CF6")
    }

    @Test func templatesAreReviewerAndTester() throws {
        #expect(PixieTemplate.all.map(\.name) == ["Reviewer", "Tester"])
        #expect(PixieTemplate.all.map(\.mascot) == [.moth, .star])
        let request = PixieTemplate.all[0].request
        #expect(request.name == "Reviewer")
        #expect(request.mascot == .moth)
        #expect(request.soul?.hasPrefix("You review code changes.") == true)
    }

    @Test func factsAreReadAddedAndRemoved() {
        let text = "# Memory\n- 2026-10-10: Small pull requests.\n- Undated fact\nplain line\n"
        let facts = PixieMemory.facts(in: text)
        #expect(
            facts == [
                PixieFact(line: 1, date: "2026-10-10", text: "Small pull requests."),
                PixieFact(line: 2, date: "", text: "Undated fact"),
            ])
        #expect(facts.map(\.id) == [1, 2])
        #expect(PixieMemory.count(text) == "2 facts")
        #expect(PixieMemory.count("- one") == "1 fact")

        #expect(PixieMemory.adding("New", to: "", on: "2026-10-13") == "- 2026-10-13: New\n")
        #expect(
            PixieMemory.adding("New", to: "# Memory", on: "2026-10-13")
                == "# Memory\n- 2026-10-13: New\n")
        #expect(
            PixieMemory.adding("New", to: "# M\n", on: "2026-10-13") == "# M\n- 2026-10-13: New\n")

        #expect(
            PixieMemory.removing(line: 1, from: text)
                == "# Memory\n- Undated fact\nplain line\n")
        #expect(PixieMemory.removing(line: 40, from: text) == text)
    }

    @Test func factDaysUseTheCalendarsTimeZone() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try #require(TimeZone(identifier: "Pacific/Auckland"))
        let date = Date(timeIntervalSince1970: 1_791_900_000)  // 2026-10-13 14:00 UTC
        #expect(PixieMemory.day(of: date, calendar: calendar) == "2026-10-14")
    }
}
