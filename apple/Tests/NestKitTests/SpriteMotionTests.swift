import Foundation
import Testing

@testable import NestKit

private func cells(_ pairs: (Int, Int)...) -> Set<GridCell> {
    Set(pairs.map { GridCell(x: $0.0, y: $0.1) })
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

    @Test func eyesAreTheTopmostSmallClosedHolesAndBlinkingFillsThem() {
        #expect(Mascot.invader.blink == .fill(cells((4, 3), (7, 3))))
        #expect(Mascot.ghost.blink == .fill(cells((4, 3), (7, 3), (4, 4), (7, 4))))
        // Not its mouth, lower down.
        #expect(Mascot.cat.blink == .fill(cells((4, 5), (7, 5))))
        // Its eye rings, five cells each, not the gap under its beak.
        #expect(
            Mascot.owl.blink
                == .fill(
                    cells(
                        (3, 3), (4, 3), (3, 4), (3, 5), (4, 5),
                        (7, 3), (8, 3), (8, 4), (7, 5), (8, 5))))
        #expect(Mascot.frog.blink == .fill(cells((3, 3), (8, 3))))
        #expect(Mascot.mushroom.blink == .fill(cells((5, 2), (6, 2))))
        #expect(Mascot.bunny.blink == .fill(cells((3, 6), (8, 6))))
        #expect(Mascot.crab.blink == .fill(cells((4, 4), (7, 4))))
        #expect(Mascot.sprout.blink == .fill(cells((4, 7), (7, 7))))
    }

    @Test func eyeHolesHoldAtMostSixCells() {
        // Six closed cells are eyes; seven are not, so the lone cell blinks instead.
        let six = ["#########", "#......##", "#########", "#.#####.#", "#########"]
        #expect(
            Mascot.blink(of: six)
                == .fill(cells((1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1))))
        let seven = ["#########", "#.......#", "#########", ".........", "....#...."]
        #expect(Mascot.blink(of: seven) == .hide(cells((4, 4))))
    }

    @Test func aMascotWithNoHolesHidesItsLoneCells() {
        #expect(Mascot.robot.blink == .hide(cells((4, 4), (7, 4))))
        #expect(Mascot.unknown.blink == .hide([]))
    }

    @Test func blinkingRowsFillTheEyesOrHideTheLoneCells() {
        #expect(Mascot.invader.rows(blinking: false) == Mascot.invader.rows)
        let invader = Mascot.invader.rows(blinking: true)
        #expect(invader[3] == "..########..")
        #expect(
            invader.enumerated().allSatisfy {
                $0.offset == 3 || $0.element == Mascot.invader.rows[$0.offset]
            })
        let robot = Mascot.robot.rows(blinking: true)
        #expect(robot[4] == "..#......#..")
        #expect(Mascot.unknown.rows(blinking: true).isEmpty)
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
