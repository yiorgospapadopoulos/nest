import Foundation

/// The words of local models (B106): Settings > Accounts' rows, the Add local model sheet,
/// the model menu's Local section, and a local chat's header, bars and cards.
public enum LocalModelText {
    public static let sectionTitle = "Local models"
    public static let sectionNote = "free, on this Mac"
    public static let menuTitle = "Local"
    public static let menuDetail = "On this Mac, free, no limits"
    public static let addTitle = "Add local model"
    public static let findTitle = "Find on this Mac"
    public static let addressTitle = "Enter address"
    public static let findNote =
        "Looked for running servers and in the LM Studio, Ollama and Hugging Face model folders."
    public static let runningTitle = "Running now"
    public static let downloadedTitle = "Downloaded, not running"
    public static let nothingRunning = "No model server is running on this Mac."
    public static let addressLabel = "Where the model runs"
    public static let keyLabel = "Key, only if the server asks for one"
    public static let noImages = "This model can't read images"
    public static let noWebSearch = "Not available on local models"
    public static let noThinking = "Thinking: not available"
    public static let notSignedIn = "Not signed in, optional"
    /// The engines a local chat can run on, the default first.
    public static let engines = [ProviderInfo.claude, "codex"]

    /// "64k" from 65 536 tokens, "1M" from a million and more; nil when unknown.
    public static func context(_ tokens: Int?) -> String? {
        guard let tokens else { return nil }
        if tokens >= 1_048_576 {
            return "\(tokens / 1_048_576)M"
        }
        return tokens >= 1024 ? "\(tokens / 1024)k" : "\(tokens)"
    }

    /// "LM Studio · localhost:1234 · 64k context", leaving out what is unknown.
    public static func place(app: String?, address: String, context tokens: Int?) -> String {
        [app, address, context(tokens).map { "\($0) context" }].compactMap { $0 }
            .joined(separator: " · ")
    }

    public static func place(_ model: LocalModel) -> String {
        place(app: model.app, address: model.address, context: model.context)
    }

    public static func place(_ model: FoundModel) -> String {
        place(app: model.app, address: model.address, context: model.context)
    }

    /// A row's state in Settings > Accounts: a word and its tone.
    public struct RowState: Sendable, Equatable {
        public let text: String
        public let tone: StatusTone
    }

    /// Not running first, since nothing else matters then.
    public static func state(_ model: LocalModel) -> RowState {
        if !model.running {
            return RowState(text: "Server not running", tone: .waiting)
        }
        switch model.tools {
        case .weak: return RowState(text: "Weak at tools", tone: .waiting)
        case .noTools: return RowState(text: "Can't use tools", tone: .failed)
        case .good, .unknown: return RowState(text: "Ready", tone: .review)
        }
    }

    /// "Start Ollama".
    public static func start(_ app: LocalApp) -> String {
        "Start \(app.title)"
    }

    /// The model menu's line under a local model.
    public static func menuDetail(_ model: LocalModel) -> String {
        if !model.running {
            return model.app.map { "\($0) is not running" } ?? "Its server is not running"
        }
        switch model.tools {
        case .weak: return "Weak at tools: edits may fail"
        case .noTools: return "Can't use tools: no edits or commands"
        case .good, .unknown:
            return [model.app, context(model.context).map { "\($0) context" }]
                .compactMap { $0 }.joined(separator: " · ").nonEmpty ?? model.address
        }
    }

    /// The quiet tag at a found model's end: added, or good at tools.
    public static func tag(_ model: FoundModel) -> String? {
        if model.added {
            return "Added"
        }
        return model.tools == .good ? "Good at tools" : nil
    }

    /// The warning under a found model that may fail as an agent.
    public static func warning(_ model: FoundModel) -> String? {
        switch model.tools {
        case .weak:
            model.weakReason ?? "Likely too weak at tools: edits and commands may fail"
        case .noTools:
            model.weakReason ?? "Can't use tools, so an agent can't edit files or run commands"
        case .good, .unknown: nil
        }
    }

    /// "Ollama models folder · start Ollama to use it".
    public static func downloaded(_ model: DownloadedModel) -> String {
        "\(model.source) · \(model.hint)"
    }

    /// The sheet's primary button.
    public static func add(count: Int) -> String {
        switch count {
        case 0: "Add models"
        case 1: "Add 1 model"
        default: "Add \(count) models"
        }
    }

    /// The line under Check: green when the server can run agents.
    public struct CheckLine: Sendable, Equatable {
        public let text: String
        public let ok: Bool
    }

    public static func checked(_ check: LocalCheck, address: String) -> CheckLine {
        guard check.ok, let server = check.server else {
            return CheckLine(text: failure(check.error, address: address), ok: false)
        }
        let what = server.app ?? "a server"
        let count = check.models.count == 1 ? "1 model" : "\(check.models.count) models"
        let engines = [
            server.worksWithClaude ? "Claude Code" : nil, server.worksWithCodex ? "Codex" : nil,
        ].compactMap { $0 }.joined(separator: " and ")
        return CheckLine(
            text: "Found \(what) at \(address) with \(count). It works with \(engines).", ok: true)
    }

    private static func failure(_ error: LocalCheckError?, address: String) -> String {
        switch error {
        case .unreachable:
            "Nothing answered at \(address). Start the app that serves your model, then Check again."
        case .noTools:
            "The server at \(address) answered, but it can't run tools, so an agent can't edit files or run commands on it."
        case .noModels:
            "The server at \(address) answered, but it has no models loaded. Load one, then Check again."
        case .unknown, nil:
            "The server at \(address) can't run agents."
        }
    }

    /// The bar above a local chat's composer while its model is weak at tools.
    public static func weakBar(_ model: LocalModel) -> String {
        model.tools == .noTools
            ? "\(model.name) can't use tools: file edits and commands will fail. Choose a model that can."
            : "\(model.name) is likely too weak at tool use: file edits and commands may fail. A model of about 20B or larger works better."
    }

    /// The card in a chat whose server did not answer.
    public static func downTitle(_ down: LocalServerDown) -> String {
        let what = down.app.map { "\($0) is" } ?? "The model's server is"
        return down.address.map { "\(what) not running at \($0)" } ?? "\(what) not running"
    }

    public static func downBody(_ down: LocalServerDown) -> String {
        let start =
            down.app.map { "Start \($0)'s server" } ?? "Start the app that serves your model"
        return "\(start), then Retry. Your message is kept and nothing was lost."
    }

    /// "Claude Code" or "Codex", as the engine a local chat runs on.
    public static func engineName(_ engine: String) -> String {
        engine == ProviderInfo.claude ? "Claude Code" : AccountText.engine(engine)
    }

    /// What a local chat on the engine can do, under its name in the submenu.
    public static func engineDetail(_ engine: String) -> String {
        switch engine {
        case ProviderInfo.claude: "Every Nest chat feature"
        case "codex": "Smaller tool set; no rewind, fork, questions or task list"
        default: ""
        }
    }

    /// The model menu's submenu title.
    public static func runsOn(_ engine: String) -> String {
        "Local chats run on \(engineName(engine))"
    }

    /// The top bar's chip when no account's limits show.
    public static func chip(tokens: Int) -> String {
        "Local · \(UsageText.tokens(tokens)) tokens today"
    }

    /// The quiet note under the local models in Settings > Accounts.
    public static func accountsNote(engine: String) -> String {
        let other = engine == ProviderInfo.claude ? "codex" : ProviderInfo.claude
        return
            "Chats on a local model run on \(engineName(engine)); to use \(engineName(other)), change Local chats run on in a model menu. No limits apply, so Usage shows token counts only."
    }

    // MARK: First run

    /// One way into Nest on the first-run welcome.
    public struct FirstRunChoice: Sendable, Equatable, Identifiable {
        public enum Kind: Sendable, Equatable {
            case claude, codex, local
        }

        public let id: Kind
        public let title: String
        public let detail: String
    }

    public static let welcomeTitle = "Welcome to Nest"
    public static let welcomeBody =
        "Chats run on your own Claude or ChatGPT plan, or free on models running on this Mac. You can add the others later in Settings › Accounts."
    public static let firstRunChoices = [
        FirstRunChoice(
            id: .claude, title: "Sign in to Claude", detail: "Your Claude plan, through Claude Code"
        ),
        FirstRunChoice(
            id: .codex, title: "Sign in to Codex", detail: "Your ChatGPT plan, through Codex"),
        FirstRunChoice(
            id: .local, title: "Use local models only",
            detail: "Free and offline. Opens Find on this Mac"),
    ]

    /// A local chat's header line after its Local label: "qwen3-coder-30b · Claude Code".
    public static func header(_ model: LocalModel, engine: String) -> String {
        "\(model.name) · \(engineName(engine))"
    }
}

extension String {
    /// Nil for an empty string.
    fileprivate var nonEmpty: String? { isEmpty ? nil : self }
}
