import Testing

@testable import NestKit

@MainActor
@Suite struct DraftBookTests {
    final class Draft {
        var text = ""
    }

    let book = DraftBook { Draft() }

    @Test func eachPaneHasItsOwnDraft() {
        let first = book.draft(for: "a")
        #expect(book.draft(for: "a") === first)
        #expect(book.draft(for: "b") !== first)
        book.remove("a")
        #expect(book.draft(for: "a") !== first)
    }

    /// What is typed while a new chat is created goes on in the chat's composer, not in
    /// the next new chat's (audit BUG-70).
    @Test func aNewChatsDraftMovesToTheChat() {
        let draft = book.draft(for: "draft-1")
        draft.text = "and also the tests"
        _ = book.draft(for: "s1")

        book.move("draft-1", to: "s1")

        #expect(book.draft(for: "s1") === draft)
        #expect(book.draft(for: "draft-1").text.isEmpty)
        book.move("missing", to: "s2")
        #expect(book.draft(for: "s2").text.isEmpty)
    }
}
