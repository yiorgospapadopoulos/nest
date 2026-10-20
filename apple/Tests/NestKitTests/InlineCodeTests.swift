import Testing

@testable import NestKit

/// A hint's `code` in mono (B91): the spaces inside it stay in the text's own font, so
/// "codex login" reads with a normal gap.
@Suite struct InlineCodeTests {
    @Test func splitsCodeAndKeepsItsSpacesPlain() {
        #expect(
            InlineCode.parts("Run `codex login` with a plan.") == [
                InlineCode(text: "Run ", isCode: false),
                InlineCode(text: "codex", isCode: true),
                InlineCode(text: " ", isCode: false),
                InlineCode(text: "login", isCode: true),
                InlineCode(text: " with a plan.", isCode: false),
            ])
    }

    @Test func plainTextAndAnUnclosedTickStayPlain() {
        #expect(InlineCode.parts("No code") == [InlineCode(text: "No code", isCode: false)])
        #expect(InlineCode.parts("a `b") == [InlineCode(text: "a `b", isCode: false)])
        #expect(InlineCode.parts("") == [])
        #expect(InlineCode.parts("`x`") == [InlineCode(text: "x", isCode: true)])
    }
}
