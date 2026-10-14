import Foundation
import Testing

@testable import NestKit

@Suite struct DictationBufferTests {
    @Test func volatileTextIsReplacedThenFinalizedAfterWhatWasTyped() {
        var buffer = DictationBuffer(text: "Please")
        buffer.apply("fix the", isFinal: false, current: "Please")
        #expect(buffer.committed == "Please")
        #expect(buffer.volatile == "fix the")
        #expect(buffer.volatileSuffix == " fix the")

        buffer.apply(" fix the work tree ", isFinal: false, current: "Please")
        #expect(buffer.volatile == "fix the work tree")

        buffer.apply("fix the worktree.", isFinal: true, current: "Please")
        #expect(buffer.committed == "Please fix the worktree.")
        #expect(buffer.volatile.isEmpty)
        #expect(buffer.volatileSuffix.isEmpty)

        buffer.apply("Then commit", isFinal: true, current: buffer.committed)
        #expect(buffer.committed == "Please fix the worktree. Then commit")
    }

    @Test func whatTheUserTypesMeanwhileIsKept() {
        var buffer = DictationBuffer(text: "")
        buffer.apply("Open the", isFinal: true, current: "")
        buffer.apply("diff", isFinal: false, current: "Open the README and")
        #expect(buffer.committed == "Open the README and")
        #expect(buffer.volatileSuffix == " diff")
        buffer.apply("diff", isFinal: true, current: "Open the README and")
        #expect(buffer.committed == "Open the README and diff")
    }

    @Test func spacingFollowsTheText() {
        #expect(DictationBuffer.join("", "Hello") == "Hello")
        #expect(DictationBuffer.join("Line\n", "next") == "Line\nnext")
        #expect(DictationBuffer.join("Hi ", "there") == "Hi there")
        #expect(DictationBuffer.join("Done", ".") == "Done.")
        #expect(DictationBuffer.join("Wait", ", what") == "Wait, what")
        #expect(DictationBuffer.join("Text", "") == "Text")
        var empty = DictationBuffer(text: "Typed")
        empty.apply("  ", isFinal: false, current: "Typed")
        #expect(empty.volatileSuffix.isEmpty)
    }

    @Test func committingKeepsTheVolatileGuess() {
        var buffer = DictationBuffer(text: "Ship it")
        buffer.apply("now please", isFinal: false, current: "Ship it")
        buffer.commit(current: "Ship it")
        #expect(buffer.committed == "Ship it now please")
        #expect(buffer.volatile.isEmpty)
        buffer.commit(current: "Ship it now please")
        #expect(buffer.committed == "Ship it now please")
    }
}

@Suite struct DictationVocabularyTests {
    func tool(_ id: String, _ input: String) -> TranscriptItem {
        let value = Fixture.decode(JSONValue.self, json: input)
        return TranscriptItem(
            id: id, content: .tool(ToolCall(id: id, name: "Read", input: value, isError: false)))
    }

    @Test func projectBranchAndFilesComeBeforeCommonTerms() {
        let items: [TranscriptItem] = [
            TranscriptItem(
                id: "u", content: .user(text: "Look at models.py and e.g. v1.2", attachments: [])),
            tool("t1", #"{"file_path": "/repo/src/SessionsStore.swift"}"#),
            tool("t2", #"{"pattern": "TODO", "path": "/repo/docs"}"#),
            TranscriptItem(
                id: "a", content: .assistant("Edited `App.tsx` and README.md.", streaming: false)),
            TranscriptItem(id: "n", content: .notice("Interrupted")),
        ]

        let terms = DictationVocabulary.terms(
            repo: "map-viewer", branch: "nest/fix-dark_mode", items: items)

        #expect(
            Array(terms.prefix(10)) == [
                "map-viewer", "map viewer", "nest/fix-dark_mode", "fix dark mode", "App.tsx",
                "App", "README.md", "README", "docs", "SessionsStore.swift",
            ])
        #expect(terms.contains("models.py"))
        #expect(terms.contains("models"))
        #expect(!terms.contains("v1.2"))
        #expect(terms.contains("pull request"))
        #expect(terms.contains("worktree"))
        // README from the transcript and from the common terms appears once.
        #expect(terms.filter { $0.lowercased() == "readme" }.count == 1)
        #expect(Set(terms.map { $0.lowercased() }).count == terms.count)
    }

    @Test func withoutContextOnlyCommonTermsRemainAndTheLimitHolds() {
        let terms = DictationVocabulary.terms(repo: nil, branch: nil, items: [])
        #expect(terms == DictationVocabulary.common)
        #expect(
            DictationVocabulary.terms(repo: "nest", branch: "main", items: [], limit: 3) == [
                "nest", "main", "Claude",
            ])
    }

    @Test func fileNamesNeedAKnownExtension() {
        #expect(
            DictationVocabulary.fileNames(in: "see a.swift, b.txt, c.unknown and Makefile.")
                == ["a.swift", "b.txt"])
        #expect(DictationVocabulary.words(of: "todo-ui") == ["todo ui"])
        #expect(DictationVocabulary.words(of: "nest").isEmpty)
    }
}
