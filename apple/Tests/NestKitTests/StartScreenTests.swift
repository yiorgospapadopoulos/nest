import Foundation
import Testing

@testable import NestKit

/// B90: the empty workspace's start screen, design I: the question, and the column of what
/// waits on the user and the project's recent chats beside the docked composer.
@Suite struct StartScreenTests {
    let now = Date(timeIntervalSince1970: 1_000_000)

    func approval(
        _ id: String, kind: ApprovalKind = .permission, session: String, repo: String = "cv-page"
    ) -> Approval {
        var approval = Fixture.approval("ap-perm")
        approval.id = id
        approval.kind = kind
        approval.sessionID = session
        approval.repo = repo
        approval.title = "Chat \(session)"
        return approval
    }

    func session(_ id: String, minutesAgo: Double, archived: Bool = false) -> Session {
        Fixture.session(
            id, title: "Chat \(id)", archived: archived,
            updatedAt: now.addingTimeInterval(-minutesAgo * 60))
    }

    /// Eight ways to ask, each naming the project or, without one, leaving it out.
    @Test func theQuestionsNameTheProject() {
        let named = (0..<StartScreen.questionCount).map {
            StartScreen.question($0, project: "nest")
        }
        #expect(
            named == [
                "What should we work on in nest?", "What's next for nest?",
                "Where should we start in nest?", "What are we building in nest today?",
                "What needs doing in nest?", "What should we fix or build in nest?",
                "What's on your mind for nest?", "What shall we tackle in nest?",
            ])
        let plain = (0..<StartScreen.questionCount).map { StartScreen.question($0, project: nil) }
        #expect(
            plain == [
                "What should we work on?", "What's next?", "Where should we start?",
                "What are we building today?", "What needs doing?",
                "What should we fix or build?", "What's on your mind?", "What shall we tackle?",
            ])
        // An index past the end wraps around.
        #expect(StartScreen.question(9, project: nil) == "What's next?")
    }

    /// Each appearance of the start screen asks the next question, never the same one twice
    /// in a row, cycling through the list.
    @Test func eachAppearanceAsksTheNextQuestion() {
        var rotation = StartQuestionRotation()
        let asked = (0..<(StartScreen.questionCount + 2)).map { _ in rotation.next() }
        #expect(asked == Array(0..<StartScreen.questionCount) + [0, 1])
        #expect(zip(asked, asked.dropFirst()).allSatisfy { $0 != $1 })
        #expect(rotation.current == 1)
        #expect(StartQuestionRotation().current == nil)
    }

    /// As the right panel lists them: approvals, failed checks, then stuck chats, each in
    /// the right panel's tone and with its Needs you line.
    @Test func waitingListsApprovalsThenFailedChecksThenStuckChats() {
        let screen = StartScreen(
            approvals: [
                approval("p1", session: "a"), approval("p2", kind: .review, session: "b"),
                approval("p3", kind: .merge, session: "c"),
            ],
            checksFailed: [session("d", minutesAgo: 5)], stuck: [session("e", minutesAgo: 9)],
            sessions: [])
        #expect(screen.waiting.map(\.chat) == ["a", "b", "c", "d", "e"])
        #expect(screen.waiting.map(\.tone) == [.waiting, .review, .review, .failed, .waiting])
        #expect(screen.waiting.map(\.title) == ["Chat a", "Chat b", "Chat c", "Chat d", "Chat e"])
        #expect(screen.waiting[0].line == NeedsYouLine.of(approval("p1", session: "a")))
        #expect(screen.waiting[3].line == NeedsYouLine(kind: "Checks failed"))
        #expect(screen.waiting[4].line.kind == "Stuck")
        #expect(Set(screen.waiting.map(\.id)).count == 5)
    }

    /// Pixies belong to no project, so their approvals stay out of a project's column.
    @Test func pixieApprovalsAreLeftOut() {
        let screen = StartScreen(
            approvals: [approval("p1", session: "a", repo: "pixie:reviewer")], checksFailed: [],
            stuck: [], sessions: [])
        #expect(screen.waiting.isEmpty)
    }

    /// The latest chats by their last activity, archived ones and the ones already waiting
    /// on the user left out, up to four.
    @Test func recentListsTheLatestChatsNotAlreadyWaiting() {
        let sessions = [
            session("old", minutesAgo: 600), session("new", minutesAgo: 2),
            session("archived", minutesAgo: 1, archived: true), session("waits", minutesAgo: 3),
            session("mid", minutesAgo: 60), session("older", minutesAgo: 900),
            session("oldest", minutesAgo: 9_000),
        ]
        let screen = StartScreen(
            approvals: [approval("p1", session: "waits")], checksFailed: [], stuck: [],
            sessions: sessions)
        #expect(screen.recent.map(\.chat) == ["new", "mid", "old", "older"])
        #expect(screen.recent.map(\.id) == screen.recent.map(\.chat))
        #expect(screen.recent.first?.title == "Chat new")
        #expect(screen.recent.first?.date == now.addingTimeInterval(-120))
        #expect(StartScreen.recentLimit == 4)
    }

    @Test func theColumnShowsWhenItHasItemsAndRoom() {
        let empty = StartScreen(approvals: [], checksFailed: [], stuck: [], sessions: [])
        #expect(!empty.showsColumn(width: 1_200))
        let recent = StartScreen(
            approvals: [], checksFailed: [], stuck: [], sessions: [session("a", minutesAgo: 1)])
        #expect(recent.showsColumn(width: StartScreen.columnMinWidth))
        #expect(!recent.showsColumn(width: StartScreen.columnMinWidth - 1))
        let waiting = StartScreen(
            approvals: [approval("p1", session: "a")], checksFailed: [], stuck: [], sessions: [])
        #expect(waiting.showsColumn(width: 900))
        #expect(StartScreen.columnMinWidth == 760)
    }

    /// Recent's short ages: under a minute "now", then whole minutes, hours and days.
    @Test func agesAreShortWholeUnits() {
        func age(_ seconds: TimeInterval) -> String {
            StartScreen.age(from: now.addingTimeInterval(-seconds), to: now)
        }
        #expect(age(20) == "now")
        #expect(age(-30) == "now")
        #expect(age(4 * 60 + 50) == "4m")
        #expect(age(59 * 60) == "59m")
        #expect(age(2 * 3600 + 40 * 60) == "2h")
        #expect(age(23 * 3600) == "23h")
        #expect(age(26 * 3600) == "1d")
        #expect(age(9 * 86_400) == "9d")
    }
}
