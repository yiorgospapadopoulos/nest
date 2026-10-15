import Foundation
import Testing

@testable import NestKit

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


@Suite struct RewindReplyTests {
    /// A conversation rewind answers the message for the composer.
    @Test func readsTheRewoundMessage() {
        let reply = Fixture.decode(
            RewindPreview.self,
            json: #"""
                {"can_rewind": true, "files_changed": [], "insertions": 0, "deletions": 0,
                 "error": null, "restore": "both", "text": "Make the button blue",
                 "attachments": [{"id": "a1", "filename": "shot.png", "media_type": "image/png", "size": 2048}]}
                """#)
        #expect(reply.restore == .both)
        #expect(reply.restoredMessage?.text == "Make the button blue")
        #expect(reply.restoredMessage?.attachments.map(\.id) == ["a1"])
        let code = Fixture.decode(
            RewindPreview.self,
            json: #"{"can_rewind": true, "restore": "code", "text": null, "attachments": []}"#)
        #expect(code.restoredMessage == nil)
        #expect(RewindRestore(rawValue: "other") == nil)
    }

    @Test func eachChoiceIsNamedAsInClaudeCode() {
        #expect(RewindRestore.conversation.label == "Restore conversation")
        #expect(RewindRestore.code.label == "Restore code")
        #expect(RewindRestore.both.label == "Restore conversation and code")
        for restore in RewindRestore.allCases {
            #expect(!restore.scope.isEmpty)
        }
        #expect(RewindRestore.code.scope.hasPrefix("Only files are restored."))
    }
}

@MainActor
@Suite struct RewindFlowTests {
    let api = FakeAPI()

    func flow(_ purpose: RewindPurpose = .rewind) -> RewindFlow {
        RewindFlow(session: "s1", message: 42, purpose: purpose, api: api)
    }

    func files(_ paths: [String] = ["a"]) -> RewindPreview {
        RewindPreview(canRewind: true, files: paths, insertions: 1, deletions: 2)
    }

    @Test func previewsBothPartsThenRestoresTheChoice() async throws {
        api.set { $0.rewinds["s1 code"] = files() }
        let flow = flow()
        #expect(flow.isLoading)
        #expect(!flow.canConfirm)
        await flow.load()
        #expect(!flow.isLoading)
        #expect(flow.choices == [.conversation, .code, .both])
        #expect(flow.files == files())
        // Like Claude Code, both parts are offered first when both can go back.
        #expect(flow.selected == .both)
        #expect(flow.canConfirm)
        #expect(flow.confirmLabel == "Restore conversation and code")
        #expect(
            Set(api.calls) == ["rewindPreview s1 42 code", "rewindPreview s1 42 conversation"])

        flow.select(.conversation)
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["rewind"] = gate.stream }
        let restoring = Task { await flow.confirm() }
        try await waitFor { flow.isRestoring }
        #expect(flow.confirmLabel == "Restoring…")
        #expect(!flow.canConfirm)
        gate.continuation.finish()
        let reply = await restoring.value
        #expect(reply?.restoredMessage?.text == "message 42")
        #expect(!flow.isRestoring)
        #expect(api.calls.last == "rewind s1 42 conversation")
    }

    @Test func aPartThatCannotGoBackSaysWhy() async {
        api.set {
            $0.rewinds["s1 code"] = RewindPreview(canRewind: false, error: "Send a message first")
            $0.rewinds["s1 conversation"] = RewindPreview(canRewind: false)
        }
        let flow = flow()
        await flow.load()
        #expect(flow.reason(.code) == "Send a message first")
        #expect(
            flow.reason(.conversation)
                == "The conversation cannot be rewound to before this message.")
        #expect(flow.reason(.both) == flow.reason(.conversation))
        #expect(flow.selected == nil)
        #expect(!flow.canConfirm)
        #expect(flow.confirmLabel == "Restore")
        #expect(await flow.confirm() == nil)
        #expect(!api.calls.contains { $0.hasPrefix("rewind ") })

        api.set { $0.rewinds["s1 code"] = RewindPreview(canRewind: false) }
        await flow.load()
        #expect(flow.reason(.code) == "The files cannot be restored to before this message.")
    }

    /// With no file changed since the message there is nothing to restore; the
    /// conversation alone can still go back.
    @Test func nothingChangedLeavesOnlyTheConversation() async {
        let flow = flow()
        await flow.load()
        #expect(flow.reason(.code) == "Nothing to restore")
        #expect(flow.reason(.both) == "Nothing to restore")
        #expect(flow.reason(.conversation) == nil)
        #expect(flow.selected == .conversation)
        flow.select(.code)
        #expect(flow.selected == .conversation)
    }

    @Test func failuresShowTheDaemonsWords() async {
        api.fail("rewindPreview", with: APIError.notFound("No such message"))
        let failed = flow()
        await failed.load()
        #expect(!failed.isLoading)
        #expect(failed.reason(.code) == "No such message")
        #expect(failed.reason(.conversation) == "No such message")
        #expect(failed.files == nil)

        api.set {
            $0.failures = [:]
            $0.rewinds["s1 code"] = files()
        }
        let flow = flow()
        await flow.load()
        api.fail("rewind", with: APIError.conflict("The chat is running."))
        #expect(await flow.confirm() == nil)
        #expect(flow.failure == "The chat is running.")
        #expect(flow.canConfirm)

        api.fail("rewind", with: CancellationError())
        #expect(await flow.confirm() == nil)
        #expect(flow.failure == CancellationError().localizedDescription)
    }

    /// Edit rewinds only the conversation, unless files changed since: then the user
    /// chooses whether they go back too.
    @Test func editAsksOnlyWhenFilesChangedSince() async {
        let plain = flow(.edit)
        await plain.load()
        #expect(plain.choices == [.conversation, .both])
        #expect(!plain.needsChoice)
        #expect(plain.selected == .conversation)

        api.set { $0.rewinds["s1 code"] = files() }
        let changed = flow(.edit)
        await changed.load()
        #expect(changed.needsChoice)
        #expect(changed.selected == .conversation)
        #expect(flow().needsChoice == false)
    }

    /// Offered whenever no turn runs, as the daemon allows it: after Stop or a failure
    /// too, but not in an archived chat (audit BUG-104).
    @Test func onlyAChatWithNoTurnRunningCanRewind() {
        for state in [SessionState.idle, .interrupted, .failed] {
            #expect(RewindFlow.isAvailable(for: Fixture.session(state: state)))
            #expect(!RewindFlow.isAvailable(for: Fixture.session(state: state, archived: true)))
        }
        for state in [SessionState.starting, .running, .waiting, .closed, .unknown] {
            #expect(!RewindFlow.isAvailable(for: Fixture.session(state: state)))
        }
        #expect(!RewindFlow.isAvailable(for: nil))
    }

    /// A pixie's runs never resume, so the daemon cannot rewind its chat.
    @Test func aPixieChatCannotRewind() {
        var chat = Fixture.session(state: .idle)
        chat.pixieID = "p1"
        #expect(!RewindFlow.isAvailable(for: chat))
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
