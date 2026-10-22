import Foundation
import Testing

@testable import NestKit

/// The words of local models (B106), as the approved mockup has them.
@Suite struct LocalModelTextTests {
    static func model(
        _ name: String, app: String? = "LM Studio", context: Int? = 65_536,
        tools: LocalToolUse = .good, reason: String? = nil, running: Bool = true
    ) -> LocalModel {
        LocalModel(
            id: "lm_\(name)", serverID: "s", model: name, name: name, address: "localhost:1234",
            app: app, context: context, tools: tools, weakReason: reason, running: running)
    }

    @Test func contextIsInThousandsOfTokens() {
        #expect(LocalModelText.context(65_536) == "64k")
        #expect(LocalModelText.context(131_072) == "128k")
        #expect(LocalModelText.context(32_768) == "32k")
        #expect(LocalModelText.context(4_096) == "4k")
        #expect(LocalModelText.context(32_000) == "31k")
        #expect(LocalModelText.context(1_048_576) == "1M")
        #expect(LocalModelText.context(500) == "500")
        #expect(LocalModelText.context(nil) == nil)
    }

    @Test func aModelsPlaceNamesItsAppAddressAndContext() {
        #expect(
            LocalModelText.place(Self.model("q"))
                == "LM Studio · localhost:1234 · 64k context")
        #expect(
            LocalModelText.place(Self.model("q", app: nil, context: nil)) == "localhost:1234")
        let found = FoundModel(
            address: "localhost:11434", app: "Ollama", model: "l", name: "l", context: 4_096)
        #expect(LocalModelText.place(found) == "Ollama · localhost:11434 · 4k context")
    }

    /// Ready, not running with the app to start, weak at tools, or without them.
    @Test func aRowSaysItsState() {
        #expect(
            LocalModelText.state(Self.model("q"))
                == LocalModelText.RowState(text: "Ready", tone: .review))
        #expect(
            LocalModelText.state(Self.model("q", running: false))
                == LocalModelText.RowState(text: "Server not running", tone: .waiting))
        #expect(
            LocalModelText.state(Self.model("q", tools: .weak))
                == LocalModelText.RowState(text: "Weak at tools", tone: .waiting))
        #expect(
            LocalModelText.state(Self.model("q", tools: .noTools))
                == LocalModelText.RowState(text: "Can't use tools", tone: .failed))
        #expect(
            LocalModelText.state(Self.model("q", tools: .weak, running: false)).text
                == "Server not running")
        #expect(LocalModelText.start(.ollama) == "Start Ollama")
        #expect(LocalModelText.start(.lmstudio) == "Start LM Studio")
    }

    /// The model menu's line: where it runs, or why it may fail, or that it is off.
    @Test func theMenuLineSaysWhatMatters() {
        #expect(LocalModelText.menuDetail(Self.model("q")) == "LM Studio · 64k context")
        #expect(
            LocalModelText.menuDetail(Self.model("q", app: nil, context: nil)) == "localhost:1234")
        #expect(
            LocalModelText.menuDetail(Self.model("q", tools: .weak))
                == "Weak at tools: edits may fail")
        #expect(
            LocalModelText.menuDetail(Self.model("q", tools: .noTools))
                == "Can't use tools: no edits or commands")
        #expect(
            LocalModelText.menuDetail(Self.model("q", app: "Ollama", running: false))
                == "Ollama is not running")
        #expect(
            LocalModelText.menuDetail(Self.model("q", app: nil, running: false))
                == "Its server is not running")
    }

    @Test func foundModelsTagTheirToolUse() {
        let good = FoundModel(address: "a", model: "m", name: "m")
        #expect(LocalModelText.tag(good) == "Good at tools")
        #expect(LocalModelText.warning(good) == nil)
        let weak = FoundModel(
            address: "a", model: "m", name: "m", tools: .weak, weakReason: "Too small.")
        #expect(LocalModelText.tag(weak) == nil)
        #expect(LocalModelText.warning(weak) == "Too small.")
        let weakWithoutWords = FoundModel(address: "a", model: "m", name: "m", tools: .weak)
        #expect(
            LocalModelText.warning(weakWithoutWords)
                == "Likely too weak at tools: edits and commands may fail")
        let none = FoundModel(address: "a", model: "m", name: "m", tools: .noTools)
        #expect(
            LocalModelText.warning(none)
                == "Can't use tools, so an agent can't edit files or run commands")
        let unknown = FoundModel(address: "a", model: "m", name: "m", tools: .unknown)
        #expect(LocalModelText.tag(unknown) == nil)
        #expect(LocalModelText.warning(unknown) == nil)
        let added = FoundModel(address: "a", model: "m", name: "m", added: true)
        #expect(LocalModelText.tag(added) == "Added")
    }

    @Test func downloadedModelsSayWhereAndWhatToDo() {
        let model = DownloadedModel(
            name: "d", source: "Ollama models folder", path: "/p", hint: "start Ollama to use it",
            start: .ollama)
        #expect(LocalModelText.downloaded(model) == "Ollama models folder · start Ollama to use it")
    }

    @Test func addSaysHowMany() {
        #expect(LocalModelText.add(count: 0) == "Add models")
        #expect(LocalModelText.add(count: 1) == "Add 1 model")
        #expect(LocalModelText.add(count: 2) == "Add 2 models")
    }

    /// The line under Check: what was found and which engines run on it, or why not.
    @Test func checkingSaysWhatAnswered() {
        let server = LocalServerInfo(
            address: "localhost:8080", app: nil, messages: false, responses: false, chat: true)
        let model = FoundModel(address: "localhost:8080", model: "m", name: "m")
        let found = LocalCheck(ok: true, server: server, models: [model])
        #expect(
            LocalModelText.checked(found, address: "localhost:8080")
                == LocalModelText.CheckLine(
                    text:
                        "Found a server at localhost:8080 with 1 model. It works with Claude Code and Codex.",
                    ok: true))
        var claudeOnly = LocalCheck(
            ok: true,
            server: LocalServerInfo(
                address: "x", app: "Ollama", messages: true, responses: false, chat: false),
            models: [model, model])
        #expect(
            LocalModelText.checked(claudeOnly, address: "x").text
                == "Found Ollama at x with 2 models. It works with Claude Code.")
        claudeOnly.server = LocalServerInfo(
            address: "x", app: nil, messages: false, responses: true, chat: false)
        #expect(
            LocalModelText.checked(claudeOnly, address: "x").text
                == "Found a server at x with 2 models. It works with Codex.")
        #expect(
            LocalModelText.checked(
                LocalCheck(ok: false, error: .unreachable), address: "localhost:8081")
                == LocalModelText.CheckLine(
                    text:
                        "Nothing answered at localhost:8081. Start the app that serves your model, then Check again.",
                    ok: false))
        #expect(
            LocalModelText.checked(
                LocalCheck(ok: false, error: .noTools), address: "localhost:5001"
            )
            .text
                == "The server at localhost:5001 answered, but it can't run tools, so an agent can't edit files or run commands on it."
        )
        #expect(
            LocalModelText.checked(LocalCheck(ok: false, error: .noModels), address: "a").text
                == "The server at a answered, but it has no models loaded. Load one, then Check again."
        )
        #expect(
            LocalModelText.checked(LocalCheck(ok: false, error: .unknown), address: "a").text
                == "The server at a can't run agents.")
        #expect(
            LocalModelText.checked(LocalCheck(ok: false), address: "a").text
                == "The server at a can't run agents.")
    }

    @Test func theWeakBarNamesTheModel() {
        #expect(
            LocalModelText.weakBar(Self.model("qwen3-4b", tools: .weak))
                == "qwen3-4b is likely too weak at tool use: file edits and commands may fail. A model of about 20B or larger works better."
        )
        #expect(
            LocalModelText.weakBar(Self.model("tiny", tools: .noTools))
                == "tiny can't use tools: file edits and commands will fail. Choose a model that can."
        )
    }

    @Test func theDownCardNamesTheAppAndAddress() {
        let down = LocalServerDown(app: "LM Studio", address: "localhost:1234", start: .lmstudio)
        #expect(LocalModelText.downTitle(down) == "LM Studio is not running at localhost:1234")
        #expect(
            LocalModelText.downBody(down)
                == "Start LM Studio's server, then Retry. Your message is kept and nothing was lost."
        )
        let bare = LocalServerDown(app: nil, address: nil, start: nil)
        #expect(LocalModelText.downTitle(bare) == "The model's server is not running")
        #expect(
            LocalModelText.downBody(bare)
                == "Start the app that serves your model, then Retry. Your message is kept and nothing was lost."
        )
    }

    @Test func enginesHaveTheirMenuWords() {
        #expect(LocalModelText.engineName("claude") == "Claude Code")
        #expect(LocalModelText.engineName("codex") == "Codex")
        #expect(LocalModelText.engineName("gemini") == "Gemini")
        #expect(LocalModelText.engineDetail("claude") == "Every Nest chat feature")
        #expect(
            LocalModelText.engineDetail("codex")
                == "Smaller tool set; no rewind, fork, questions or task list")
        #expect(LocalModelText.engineDetail("gemini") == "")
        #expect(LocalModelText.engines == ["claude", "codex"])
        #expect(LocalModelText.runsOn("codex") == "Local chats run on Codex")
    }

    @Test func theChipCountsTodaysTokens() {
        #expect(LocalModelText.chip(tokens: 48_600) == "Local · 49k tokens today")
        #expect(LocalModelText.chip(tokens: 0) == "Local · 0 tokens today")
    }

    @Test func accountsNoteNamesTheEngine() {
        #expect(
            LocalModelText.accountsNote(engine: "claude")
                == "Chats on a local model run on Claude Code; to use Codex, change Local chats run on in a model menu. No limits apply, so Usage shows token counts only."
        )
        #expect(
            LocalModelText.accountsNote(engine: "codex")
                == "Chats on a local model run on Codex; to use Claude Code, change Local chats run on in a model menu. No limits apply, so Usage shows token counts only."
        )
    }

    /// The first-run welcome's three ways in.
    @Test func theWelcomeOffersThreeWays() {
        #expect(LocalModelText.welcomeTitle == "Welcome to Nest")
        #expect(
            LocalModelText.firstRunChoices.map(\.id) == [.claude, .codex, .local])
        #expect(
            LocalModelText.firstRunChoices.map(\.title) == [
                "Sign in to Claude", "Sign in to Codex", "Use local models only",
            ])
        #expect(
            LocalModelText.firstRunChoices.map(\.detail) == [
                "Your Claude plan, through Claude Code", "Your ChatGPT plan, through Codex",
                "Free and offline. Opens Find on this Mac",
            ])
    }

    @Test func aChatHeaderNamesTheModelAndEngine() {
        #expect(LocalModelText.header(Self.model("q"), engine: "claude") == "q · Claude Code")
    }
}
