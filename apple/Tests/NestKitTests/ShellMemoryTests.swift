import Foundation
import Testing

@testable import NestKit

/// B59 wave 3: `!` runs a shell command, `#` saves a memory, as in Claude Code.
@Suite struct ComposerInputTests {
    @Test func aBangIsAShellCommandWhereShellCommandsRun() {
        #expect(ComposerInput.of("!git status ", bash: true, memory: true) == .bash("git status"))
        #expect(ComposerInput.of("!", bash: true, memory: true) == .bash(""))
        // Where `!` is not offered it is plain text.
        #expect(ComposerInput.of("!git status", bash: false, memory: true) == .message)
        #expect(ComposerInput.of(" !ls", bash: true, memory: true) == .message)
    }

    /// `#` then not `#`: a Markdown heading typed as "## ..." stays a message.
    @Test func aHashIsAMemoryButAHeadingIsNot() {
        #expect(
            ComposerInput.of("# Run make check\n first", bash: true, memory: true)
                == .memory("Run make check\n first"))
        #expect(ComposerInput.of("#note", bash: false, memory: true) == .memory("note"))
        #expect(ComposerInput.of("## Heading", bash: true, memory: true) == .message)
        #expect(ComposerInput.of("#note", bash: true, memory: false) == .message)
        #expect(ComposerInput.of("Hello", bash: true, memory: true) == .message)
        #expect(ComposerInput.of("", bash: true, memory: true) == .message)
    }

    @Test func shellCommandsRunOnlyInTheUsersOwnChats() {
        #expect(ComposerInput.canRunShell(in: Fixture.session(state: .running)))
        var pixie = Fixture.session()
        pixie.pixieID = "p1"
        #expect(!ComposerInput.canRunShell(in: pixie))
        var started = Fixture.session()
        started.startedByPixie = "p1"
        #expect(!ComposerInput.canRunShell(in: started))
        #expect(!ComposerInput.canRunShell(in: nil))
    }
}

@Suite struct BashBlocksTests {
    @Test func leadingBlocksBecomeBashRowsAndTheRestTheBubble() {
        let text =
            "<bash-input>git status</bash-input>\n<bash-stdout> M a.py\n</bash-stdout><bash-stderr></bash-stderr>\n"
            + "<bash-input>false</bash-input>\n<bash-stdout></bash-stdout><bash-stderr>oops</bash-stderr>"
            + "\n\nWhat changed?"
        let split = BashBlocks.split(text)
        #expect(
            split.blocks == [
                BashBlock(command: "git status", stdout: " M a.py\n", stderr: ""),
                BashBlock(command: "false", stdout: "", stderr: "oops"),
            ])
        #expect(split.rest == "What changed?")
        #expect(split.blocks[0].output == " M a.py\n")
        #expect(split.blocks[1].output == "oops")
        #expect(
            BashBlock(command: "x", stdout: "out", stderr: "err").output == "out\nerr")
    }

    @Test func plainAndBrokenTextStaysAsItIs() {
        #expect(BashBlocks.split("Hello").blocks.isEmpty)
        #expect(BashBlocks.split("Hello").rest == "Hello")
        let broken = "<bash-input>ls</bash-input>\n<bash-stdout>half"
        #expect(BashBlocks.split(broken).blocks.isEmpty)
        #expect(BashBlocks.split(broken).rest == broken)
        let only =
            "<bash-input>ls</bash-input>\n<bash-stdout>a</bash-stdout><bash-stderr></bash-stderr>"
        #expect(BashBlocks.split(only).rest == "")
        #expect(BashBlocks.split(only).blocks.count == 1)
        let glued =
            "<bash-input>ls</bash-input>\n<bash-stdout>a</bash-stdout><bash-stderr></bash-stderr>tail"
        #expect(BashBlocks.split(glued).rest == "tail")
    }

    @Test func contextsGoBeforeTheTypedText() {
        #expect(BashBlocks.message("Hi", contexts: []) == "Hi")
        #expect(BashBlocks.message("Hi", contexts: ["a", "b"]) == "a\nb\n\nHi")
    }
}

@Suite struct ShellAndMemoryModelTests {
    @Test func readsAShellRun() {
        let run = Fixture.decode(
            ShellRun.self,
            json: #"""
                {"command": "sleep 999", "exit_code": null, "output": "", "truncated": true,
                 "timed_out": true, "context": "<bash-input>sleep 999</bash-input>"}
                """#)
        #expect(run.exitCode == nil)
        #expect(run.notes == ["timed out after 2 minutes", "output cut"])
        let failed = ShellRun(
            command: "false", exitCode: 1, output: "", truncated: false, timedOut: false,
            context: "c")
        #expect(failed.notes == ["exit 1"])
        #expect(
            ShellRun(
                command: "true", exitCode: 0, output: "", truncated: false, timedOut: false,
                context: "c"
            ).notes.isEmpty)
    }

    @Test func memoryGoesToTheProjectOrTheUser() {
        #expect(MemoryScope.choices(pixie: false) == [.project, .user])
        #expect(MemoryScope.choices(pixie: true) == [.user])
        #expect(MemoryScope.project.label == "Project memory")
        #expect(MemoryScope.user.label == "User memory")
        let saved = Fixture.decode(
            SavedMemory.self,
            json: #"{"path": "/r/CLAUDE.md", "scope": "project", "line": "- x"}"#)
        #expect(saved.confirmation == "Saved to project memory")
        #expect(
            SavedMemory(path: "/h/.claude/CLAUDE.md", scope: .user, line: "- y").confirmation
                == "Saved to user memory")
    }
}

@MainActor
@Suite struct BashStoreTests {
    let api = FakeAPI()
    let store: BashStore

    init() {
        store = BashStore(api: api)
    }

    @Test func aCommandShowsAtOnceThenItsOutput() async throws {
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["runShell"] = gate.stream }
        let running = Task { await store.run("ls", chat: "s1") }
        try await waitFor { !store.rows(chat: "s1").isEmpty }
        #expect(store.rows(chat: "s1")[0].command == "ls")
        #expect(store.rows(chat: "s1")[0].isRunning)
        gate.continuation.finish()
        await running.value
        let row = store.rows(chat: "s1")[0]
        #expect(!row.isRunning)
        #expect(row.run?.output == "output of ls")
        #expect(api.calls == ["runShell s1 ls"])
        #expect(store.rows(chat: "other").isEmpty)
    }

    @Test func aFailureShowsInTheRow() async {
        api.fail("runShell", with: APIError.conflict("A pixie's chat cannot run shell commands."))
        await store.run("ls", chat: "s1")
        let row = store.rows(chat: "s1")[0]
        #expect(row.failure == "A pixie's chat cannot run shell commands.")
        #expect(!row.isRunning)
        api.fail("runShell", with: CancellationError())
        await store.run("ls", chat: "s1")
        #expect(store.rows(chat: "s1")[1].failure == CancellationError().localizedDescription)
    }

    /// The next message carries the finished commands' contexts; those rows then leave,
    /// as the sent message shows them. A command still running waits for the one after.
    @Test func theNextMessageCarriesTheContexts() async throws {
        await store.run("ls", chat: "s1")
        api.fail("runShell")
        await store.run("bad", chat: "s1")
        api.set {
            $0.failures = [:]
            $0.gates["runShell"] = AsyncStream<Void>.makeStream().stream
        }
        Task { await store.run("slow", chat: "s1") }
        try await waitFor { store.rows(chat: "s1").count == 3 }

        let outgoing = store.outgoing("Why?", chat: "s1")
        #expect(outgoing.text == "context of ls\n\nWhy?")
        store.sent(outgoing.rows, chat: "s1")
        #expect(store.rows(chat: "s1").map(\.command) == ["slow"])

        let none = store.outgoing("Hi", chat: "s2")
        #expect(none.text == "Hi")
        #expect(none.rows.isEmpty)
    }
}

@MainActor
@Suite struct BashTranscriptTests {
    let api = FakeAPI()

    @Test func aSentMessageShowsItsCommandsAsBashRows() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        let text =
            #"<bash-input>ls</bash-input>\n<bash-stdout>a.py</bash-stdout><bash-stderr></bash-stderr>\n\nWhat is a.py?"#
        transcript.receive(
            Fixture.event(
                EventType.sessionUserMessage, #"{"text": "\#(text)", "attachments": []}"#, id: 3)
        )
        #expect(
            transcript.items.map(\.content) == [
                .bash(BashBlock(command: "ls", stdout: "a.py", stderr: "")),
                .user(text: "What is a.py?", attachments: []),
            ])
        #expect(transcript.items.map(\.eventID) == [3, 3])
        #expect(transcript.lastUserMessage == 3)
    }

    @Test func aMessageOfOnlyCommandsHasNoBubble() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        let text =
            #"<bash-input>ls</bash-input>\n<bash-stdout>a</bash-stdout><bash-stderr></bash-stderr>"#
        transcript.receive(
            Fixture.event(
                EventType.sessionUserMessage, #"{"text": "\#(text)", "attachments": []}"#, id: 3)
        )
        #expect(transcript.items.count == 1)
        #expect(transcript.visibleItems.count == 1)
    }
}

/// Tool results may carry images (Read of an image, screenshot tools).
@MainActor
@Suite struct ToolImageTests {
    let api = FakeAPI()

    static let image = #"[{"attachment_id": "img1", "media_type": "image/png"}]"#

    @Test func toolResultsKeepTheirImages() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        transcript.receive(
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]}"#,
                id: 1))
        transcript.receive(
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "tool_result", "tool_use_id": "t1", "content": "", "is_error": false, "images": \#(Self.image)}]}"#,
                id: 2))
        guard case .tool(let call) = transcript.items.first?.content else {
            Issue.record("no tool row")
            return
        }
        #expect(call.images == [ToolImage(attachmentID: "img1", mediaType: "image/png")])
        #expect(call.images.map(\.id) == ["img1"])
    }

    /// A subagent's tool images show under its agent call, in order.
    @Test func aSubagentsImagesShowAsASteps() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        transcript.receive(
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "tool_use", "id": "a1", "name": "Agent", "input": {}}]}"#,
                id: 1))
        transcript.receive(
            Fixture.event(
                EventType.sessionMessage,
                #"{"parent_tool_use_id": "a1", "blocks": [{"type": "tool_result", "tool_use_id": "t9", "content": "x", "images": \#(Self.image)}, {"type": "tool_result", "tool_use_id": "t8", "content": "y"}]}"#,
                id: 2))
        guard case .tool(let call) = transcript.items.first?.content else {
            Issue.record("no agent row")
            return
        }
        let images = [ToolImage(attachmentID: "img1", mediaType: "image/png")]
        #expect(call.steps.map(\.kind) == [.images(images)])
        #expect(call.steps[0].line == "1 image")
        #expect(CallStep(id: "x", kind: .images(images + images)).line == "2 images")
    }

    @Test func imagesLoadOnceWithTheDeviceToken() async throws {
        let images = AttachmentImages(api: api)
        #expect(images.data(for: "img1") == nil)
        await images.load("img1")
        await images.load("img1")
        #expect(images.data(for: "img1") == Data("image img1".utf8))
        #expect(api.calls == ["attachmentData img1"])

        api.fail("attachmentData", with: APIError.notFound("unknown attachment"))
        await images.load("gone")
        #expect(images.data(for: "gone") == nil)
        #expect(images.failed("gone"))
        #expect(!images.failed("img1"))
    }
}

/// @ suggests files in every chat: plain folders and pixie chats too (B59).
@MainActor
@Suite struct FileSuggestionsEverywhereTests {
    let api = FakeAPI()

    @Test func aPixieComposerSuggestsFilesButNoCommands() async {
        let store = CompletionStore(api: api)
        api.set { $0.files["no"] = ["notes.md"] }
        await store.searchFiles(session: "pixie-chat", query: "no")
        let files = store.suggestions(
            text: "@no", caret: 3, session: "pixie-chat", repo: "", filesOnly: true)
        #expect(files?.items.map(\.label) == ["notes.md"])
        #expect(
            store.suggestions(
                text: "/he", caret: 3, session: "pixie-chat", repo: "", filesOnly: true)
                == nil)
    }
}
