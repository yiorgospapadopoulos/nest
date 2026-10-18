import Foundation
import Testing

@testable import NestKit

private func ink(_ hex: String, _ opacity: Double = 1) -> SpriteInk {
    SpriteInk(hex: hex, opacity: opacity)
}

private func pixie(_ id: String) -> Pixie {
    var pixie = Fixture.decode(Pixie.self, "pixie")
    pixie.id = id
    pixie.slug = id
    return pixie
}

@Suite struct SpriteMotionTests {
    @Test func hopsUpOneCellOnTheMiddleTwoOfEveryFourSteps() {
        let lifted = (0..<8).map { SpriteMotion.frame(at: Double($0) * 170 + 5).lifted }
        #expect(lifted == [false, true, true, false, false, true, true, false])
        // Hard steps: the whole step holds, right up to its end.
        #expect(SpriteMotion.frame(at: 169.9) == .rest)
        #expect(SpriteMotion.frame(at: 170).lifted)
        #expect(SpriteMotion.frame(at: 509.9).lifted)
        #expect(!SpriteMotion.frame(at: 510).lifted)
    }

    @Test func blinksWhileLiftedOnEveryThirdHop() {
        let blinking = (0..<12).map { SpriteMotion.frame(at: Double($0) * 170 + 1).blinking }
        #expect(
            blinking == [
                false, false, false, false,
                false, false, false, false,
                false, true, true, false,
            ])
        // The next cycle of three hops starts over.
        #expect(!SpriteMotion.frame(at: 2040 + 171).blinking)
        #expect(SpriteMotion.frame(at: 2040 * 5 + 1360 + 340).blinking)
        #expect(SpriteMotion.frame(at: 1360 + 170) == SpriteFrame(lifted: true, blinking: true))
    }

    @Test func clocksBeforeTheEpochStillStepForward() {
        #expect(SpriteMotion.frame(at: -1) == .rest)
        #expect(SpriteMotion.frame(at: -170 * 2 - 1).lifted)
        #expect(SpriteMotion.frame(at: -340 - 1) == SpriteFrame(lifted: true, blinking: true))
    }

    @Test func phasesAreStableAndSpreadAcrossTheCycle() {
        #expect(SpriteMotion.phase(of: "reviewer") == SpriteMotion.phase(of: "reviewer"))
        // FNV-1a of the key's UTF-16 units, as the iPhone hashes it, in whole milliseconds
        // of the three-hop cycle.
        #expect(SpriteMotion.phase(of: "") == Double(2_166_136_261 % 2040))
        #expect(SpriteMotion.phase(of: "a") == Double(3_826_002_220 % 2040))
        // One unit, not UTF-8's two bytes.
        #expect(SpriteMotion.phase(of: "\u{E9}") == Double(1_812_687_940 % 2040))
        let phases = Set(
            ["reviewer", "watcher", "tester", "scout", "bugs"].map(SpriteMotion.phase))
        #expect(phases.count == 5)
        #expect(phases.allSatisfy { $0 >= 0 && $0 < 2040 })
    }

    @Test func eachCellCodeHasItsToneOfThePixiesColour() {
        let violet = "#8B7CF6"
        #expect(SpriteTones.ink(of: "#", color: violet, blinking: false) == ink("#8B7CF6"))
        // Shade 30% toward black, light 70% and wing 45% toward white, per channel, rounded.
        #expect(SpriteTones.ink(of: "+", color: violet, blinking: false) == ink("#6157AC"))
        #expect(SpriteTones.ink(of: "o", color: violet, blinking: false) == ink("#DCD8FC"))
        #expect(
            SpriteTones.ink(of: "*", color: violet, blinking: false) == ink("#BFB7FA", 0.85))
        #expect(SpriteTones.ink(of: "+", color: "#E5484D", blinking: false) == ink("#A03236"))
        #expect(SpriteTones.ink(of: "o", color: "#FFC53D", blinking: false) == ink("#FFEEC5"))
        #expect(SpriteTones.ink(of: "*", color: "#FFC53D", blinking: false)?.hex == "#FFDF94")
        // Eyes and ink marks are the ink in any colour.
        #expect(SpriteTones.ink(of: "e", color: violet, blinking: false) == ink("#221E29"))
        #expect(SpriteTones.ink(of: "k", color: "#E5484D", blinking: false) == ink("#221E29"))
        #expect(SpriteTones.ink(of: ".", color: violet, blinking: false) == nil)
        #expect(SpriteTones.ink(of: "x", color: violet, blinking: false) == nil)
    }

    @Test func blinkingDrawsTheEyesInTheBodyColourOnly() {
        #expect(SpriteTones.ink(of: "e", color: "#46A758", blinking: true) == ink("#46A758"))
        #expect(SpriteTones.ink(of: "k", color: "#46A758", blinking: true) == ink("#221E29"))
        #expect(SpriteTones.ink(of: "+", color: "#46A758", blinking: true) == ink("#31753E"))
    }

    @Test func aColourIsReadInCapitalsAndAnUnreadableOneIsTheStandardViolet() {
        #expect(SpriteTones.ink(of: "#", color: "#8b7cf6", blinking: false) == ink("#8B7CF6"))
        #expect(SpriteTones.ink(of: "#", color: "teal", blinking: false) == ink("#8B7CF6"))
        #expect(SpriteTones.ink(of: "o", color: "teal", blinking: false) == ink("#DCD8FC"))
        #expect(SpriteTones.ink(of: "e", color: "teal", blinking: true) == ink("#8B7CF6"))
    }

    @Test func aMascotsLayersHoldEveryDrawnCellOnceByCode() throws {
        let rest = Mascot.bluebell.layers(color: "#8B7CF6", blinking: false)
        #expect(
            rest.map(\.ink)
                == ["#", "+", "o", "*", "e", "k"].map {
                    SpriteTones.ink(of: $0, color: "#8B7CF6", blinking: false)!
                })
        #expect(rest.map(\.cells.count) == [60, 12, 26, 30, 2, 2])
        let eyes = try #require(rest.first { $0.cells.contains(GridCell(x: 4, y: 5)) })
        #expect(eyes.cells == [GridCell(x: 4, y: 5), GridCell(x: 9, y: 5)])
        #expect(eyes.ink == ink("#221E29"))
        let drawn = Set(rest.flatMap(\.cells))
        #expect(drawn.count == 14 * 14 - 64)
        #expect(!drawn.contains(GridCell(x: 0, y: 0)))
        // A code a mascot lacks gives no layer: Rose has no ink marks.
        #expect(Mascot.rose.layers(color: "#E5484D", blinking: false).count == 5)
        #expect(
            GridCell.all("#", in: ["#.#", ".+#"])
                == [GridCell(x: 0, y: 0), GridCell(x: 2, y: 0), GridCell(x: 2, y: 1)])
    }

    @Test func blinkingLayersOnlyRepaintTheEyes() {
        let rest = Mascot.frost.layers(color: "#0090FF", blinking: false)
        let blink = Mascot.frost.layers(color: "#0090FF", blinking: true)
        #expect(blink.map(\.cells) == rest.map(\.cells))
        #expect(blink[4].cells == [GridCell(x: 4, y: 4), GridCell(x: 9, y: 4)])
        #expect(blink[4].ink == ink("#0090FF"))
        #expect(Array(blink.prefix(4)) == Array(rest.prefix(4)))
        #expect(Mascot.unknown.layers(color: "#0090FF", blinking: true).isEmpty)
    }

    @Test func aTeamIconFillsFourCellsLeaderFirst() {
        #expect(TeamIcon.fill([String]()).isEmpty)
        #expect(TeamIcon.fill(["a"]) == ["a", "a", "a", "a"])
        #expect(TeamIcon.fill(["a", "b"]) == ["a", "b", "a", "b"])
        #expect(TeamIcon.fill(["a", "b", "c"]) == ["a", "b", "c", "a"])
        #expect(TeamIcon.fill(["a", "b", "c", "d"]) == ["a", "b", "c", "d"])
        #expect(TeamIcon.fill(["a", "b", "c", "d", "e"]) == ["a", "b", "c", "d"])
    }

    @Test func aTeamIconTakesTheEntrysKnownMembersWithTheirCallState() throws {
        let entry: ChatPixieEntry = try NestJSON.decoder.decode(
            ChatPixieEntry.self,
            from: Data(
                """
                {"kind": "team", "pixie_id": null, "team_id": "qa", "state": "running",
                 "calls": [], "members": [
                   {"pixie_id": "stylist", "leader": false, "state": "done"},
                   {"pixie_id": "gone", "leader": false, "state": "running"},
                   {"pixie_id": "bugs", "leader": true, "state": "running"},
                   {"pixie_id": "scout", "leader": false, "state": null}
                 ]}
                """.utf8))
        let known = [pixie("scout"), pixie("bugs"), pixie("stylist")]
        let icon = TeamIcon.cells(of: entry, pixies: known)
        #expect(icon.map(\.pixie.id) == ["bugs", "stylist", "scout", "bugs"])
        #expect(icon.map(\.working) == [true, false, false, true])
        // Each cell keeps its own clock, so copies of one pixie do not hop in unison.
        #expect(icon.map(\.phaseKey) == ["bugs#0", "stylist#1", "scout#2", "bugs#3"])
        #expect(TeamIcon.cells(of: entry, pixies: []).isEmpty)
    }

    @Test func aPixiesChatWorksWhileStartingOrRunning() {
        #expect(SessionState.starting.isWorking)
        #expect(SessionState.running.isWorking)
        #expect(!SessionState.waiting.isWorking)
        #expect(!SessionState.idle.isWorking)
    }
}
