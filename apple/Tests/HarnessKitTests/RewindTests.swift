import Foundation
import Testing

@testable import HarnessKit

@Suite struct RewindPreviewTests {
    @Test func readsClaudeCodesListOfChangedFiles() {
        let preview = Fixture.decode(
            RewindPreview.self,
            json: #"""
                {"can_rewind": true, "files_changed": ["src/a.ts", "src/b.ts"],
                 "insertions": 12, "deletions": 4, "error": null}
                """#)
        #expect(
            preview
                == RewindPreview(
                    canRewind: true, files: ["src/a.ts", "src/b.ts"], insertions: 12, deletions: 4))
        #expect(preview.filesChanged == 2)
        #expect(preview.summary == "2 files change: +12 -4")
    }

    @Test func readsACountAndMissingFields() {
        let counted = Fixture.decode(
            RewindPreview.self, json: #"{"can_rewind": true, "files_changed": 1}"#)
        #expect(counted.files.isEmpty)
        #expect(counted.filesChanged == 1)
        #expect(counted.summary == "1 file changes: +0 -0")
        let refused = Fixture.decode(
            RewindPreview.self, json: #"{"can_rewind": false, "error": "No checkpoint"}"#)
        #expect(refused.filesChanged == 0)
        #expect(refused.error == "No checkpoint")
        #expect(refused.summary == "No files changed since this message.")
    }
}

@MainActor
@Suite struct RewindFlowTests {
    let api = FakeAPI()

    func flow() -> RewindFlow {
        RewindFlow(session: "s1", message: 42, api: api)
    }

    @Test func previewsThenRestoresTheFiles() async {
        let preview = RewindPreview(canRewind: true, files: ["a"], insertions: 1, deletions: 2)
        api.set { $0.rewinds["s1"] = preview }
        let flow = flow()
        #expect(flow.isLoading)
        #expect(!flow.canRestore)
        await flow.load()
        #expect(!flow.isLoading)
        #expect(flow.preview == preview)
        #expect(flow.failure == nil)
        #expect(flow.canRestore)

        #expect(await flow.restore())
        #expect(!flow.isRestoring)
        #expect(api.calls == ["rewindPreview s1 42", "rewind s1 42"])
        #expect(RewindFlow.scope.hasPrefix("Only files are restored."))
    }

    @Test func aPreviewThatCannotRewindSaysWhy() async {
        api.set { $0.rewinds["s1"] = RewindPreview(canRewind: false, error: "No checkpoint") }
        let flow = flow()
        await flow.load()
        #expect(flow.failure == "No checkpoint")
        #expect(!flow.canRestore)
        #expect(await flow.restore() == false)
        #expect(!api.calls.contains("rewind s1 42"))

        api.set { $0.rewinds["s1"] = RewindPreview(canRewind: false) }
        await flow.load()
        #expect(flow.failure == "The files cannot be restored to before this message.")
    }

    @Test func failuresShowTheDaemonsWords() async {
        api.fail("rewindPreview", with: APIError.notFound("No such message"))
        let failed = flow()
        await failed.load()
        #expect(failed.failure == "No such message")
        #expect(failed.preview == nil)
        #expect(!failed.isLoading)

        api.set { $0.failures = [:] }
        let flow = flow()
        await flow.load()
        api.fail("rewind", with: APIError.conflict("The chat is running.", files: []))
        #expect(await flow.restore() == false)
        #expect(flow.failure == "The chat is running.")
        #expect(flow.canRestore)

        api.fail("rewind", with: CancellationError())
        #expect(await flow.restore() == false)
        #expect(flow.failure == CancellationError().localizedDescription)
    }

    @Test func onlyAnIdleOpenChatCanRestore() {
        #expect(RewindFlow.isAvailable(for: Fixture.session(state: .idle)))
        #expect(!RewindFlow.isAvailable(for: Fixture.session(state: .running)))
        #expect(!RewindFlow.isAvailable(for: Fixture.session(state: .waiting)))
        #expect(!RewindFlow.isAvailable(for: Fixture.session(state: .idle, archived: true)))
        #expect(!RewindFlow.isAvailable(for: nil))
    }

    @Test func theRestoreNoticeShowsInTheTranscript() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        transcript.receive(
            Fixture.event(
                EventType.sessionNotice,
                #"{"kind": "files_restored", "text": "Files restored to before a message"}"#,
                id: 7))
        #expect(transcript.items.map(\.content) == [.notice("Files restored to before a message")])
    }
}
