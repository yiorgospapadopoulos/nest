import Foundation

/// What a chat on some engine cannot do, as the daemon names it (B91, D113). Clients hide
/// what an engine lists; the daemon refuses it with `unsupported_feature`.
public enum ProviderFeature: String, UnknownSafeEnum {
    /// Rewinding the conversation or the files, and editing a sent message.
    case rewind
    case fork
    case slashCommands = "slash_commands"
    /// Stopping one background task or subagent while the turn goes on.
    case stopTask = "stop_task"
    /// Taking back a message already written into the running turn.
    case withdraw
    case planReview = "plan_review"
    case questions
    case subagents
    case nestTools = "nest_tools"
    case taskList = "task_list"
    case pixies
    /// The composer's `#` memory, which goes into CLAUDE.md, a file only Claude Code reads.
    case memory
    /// A pixie's own skill list, which only Claude runs take; on another engine its details
    /// leave Skills out.
    case pixieSkills = "pixie_skills"
    case unknown

    /// What a chat without it cannot do, for a refusal that came without words.
    public var refusal: String {
        switch self {
        case .rewind: "be rewound"
        case .fork: "be forked"
        case .slashCommands: "run slash commands"
        case .stopTask: "stop a single task"
        case .withdraw: "take back a message sent into the turn"
        case .planReview: "review a plan"
        case .questions: "ask questions"
        case .subagents: "run subagents"
        case .nestTools: "use Nest's tools"
        case .taskList: "keep a task list"
        case .pixies: "call pixies"
        case .memory: "save a memory to CLAUDE.md"
        case .pixieSkills: "keep a pixie's own skill list"
        case .unknown: "do that"
        }
    }
}

/// Whether an engine can run chats on this Mac (B107); Claude and Codex are always ready.
public enum EngineState: String, UnknownSafeEnum {
    case ready
    case notInstalled = "not_installed"
    case installing
    case installFailed = "install_failed"
    case unknown
}

/// How the user signs in to an engine (B107).
public enum EngineSignIn: String, UnknownSafeEnum {
    /// The engine's own sign-in page (Claude, Codex).
    case browser
    /// A key pasted in Settings, which the daemon keeps in the Keychain (Gemini).
    case apiKey = "api_key"
    /// The engine's own login command, run in Terminal (OpenCode, Cursor).
    case terminal
    case unknown
}

/// An engine a new chat can run on, from `GET /api/providers` (B91).
public struct ProviderInfo: Decodable, Sendable, Hashable, Identifiable {
    /// The engine chats run on when none is chosen, and every chat from before B91.
    public static let claude = "claude"

    /// What a new chat's `provider` is set to.
    public var name: String
    public var displayName: String
    /// Nil when Nest does not check (Claude) or could not ask; false keeps the engine
    /// offered, and its chats are refused until the user signs in.
    public var signedIn: Bool?
    /// What to tell the user while `signedIn` is false.
    public var signInHint: String?
    /// Who the engine is signed in as; the same fields as Claude's account.
    public var account: ClaudeAccount?
    /// Features this app does not know are left out.
    public var unsupported: Set<ProviderFeature>
    /// The installed engine's version, when known (B107).
    public var version: String?
    /// False labels the engine "untested".
    public var tested: Bool
    /// False: Nest cannot block the engine's git commands.
    public var gitGuard: Bool
    public var state: EngineState
    /// Why it is not installed, or why installing failed, in plain words.
    public var stateDetail: String?
    public var signIn: EngineSignIn
    /// The command the user runs in Terminal to sign in, such as `agent login`, for a
    /// terminal sign-in.
    public var loginCommand: String?

    public var id: String { name }

    public init(
        name: String, displayName: String, signedIn: Bool? = nil, signInHint: String? = nil,
        account: ClaudeAccount? = nil, unsupported: Set<ProviderFeature> = [],
        version: String? = nil, tested: Bool = true, gitGuard: Bool = true,
        state: EngineState = .ready, stateDetail: String? = nil, signIn: EngineSignIn = .browser,
        loginCommand: String? = nil
    ) {
        self.name = name
        self.displayName = displayName
        self.signedIn = signedIn
        self.signInHint = signInHint
        self.account = account
        self.unsupported = unsupported
        self.version = version
        self.tested = tested
        self.gitGuard = gitGuard
        self.state = state
        self.stateDetail = stateDetail
        self.signIn = signIn
        self.loginCommand = loginCommand
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        name = try container.decode(String.self, forKey: .name)
        displayName = try container.decode(String.self, forKey: .displayName)
        signedIn = try container.decodeIfPresent(Bool.self, forKey: .signedIn)
        signInHint = try container.decodeIfPresent(String.self, forKey: .signInHint)
        account = try container.decodeIfPresent(ClaudeAccount.self, forKey: .account)
        unsupported = Set(
            try container.decode([ProviderFeature].self, forKey: .unsupported)
                .filter { $0 != .unknown })
        // A daemon before B107 sends none of these: Claude and Codex as they were.
        version = try container.decodeIfPresent(String.self, forKey: .version)
        tested = try container.decodeIfPresent(Bool.self, forKey: .tested) ?? true
        gitGuard = try container.decodeIfPresent(Bool.self, forKey: .gitGuard) ?? true
        state = try container.decodeIfPresent(EngineState.self, forKey: .state) ?? .ready
        stateDetail = try container.decodeIfPresent(String.self, forKey: .stateDetail)
        signIn = try container.decodeIfPresent(EngineSignIn.self, forKey: .signIn) ?? .browser
        loginCommand = try container.decodeIfPresent(String.self, forKey: .loginCommand)
    }

    /// Whether a new chat may run on it: ready, and not refused for a sign-in Nest checks
    /// itself. Claude and Codex stay offered signed out and say so at sending (B91).
    public var offeredForNewChats: Bool {
        state == .ready && (signIn == .browser || signedIn != false)
    }

    /// Whether a pixie may run on it: ready, and Nest can block its pushes unless the user
    /// lets agents push, which the daemon reports as `gitGuard`; it refuses the others
    /// (B107, D160).
    public var offeredForPixies: Bool {
        state == .ready && gitGuard
    }

    enum CodingKeys: String, CodingKey {
        case name, account, unsupported, version, tested, state
        case displayName = "display_name"
        case signedIn = "signed_in"
        case signInHint = "sign_in_hint"
        case gitGuard = "git_guard"
        case stateDetail = "state_detail"
        case signIn = "sign_in"
        case loginCommand = "login_command"
    }
}

/// `engine.state`: installing an engine moved on, or its state changed (B107). Clients read
/// the engines again.
public struct EngineStateChange: Decodable, Sendable, Hashable {
    public var name: String
    public var state: EngineState
    public var version: String?
    public var stateDetail: String?

    public init(
        name: String, state: EngineState, version: String? = nil, stateDetail: String? = nil
    ) {
        self.name = name
        self.state = state
        self.version = version
        self.stateDetail = stateDetail
    }

    enum CodingKeys: String, CodingKey {
        case name, state, version
        case stateDetail = "state_detail"
    }
}

/// `GET /api/providers`: the default engine first.
public struct ProviderList: Decodable, Sendable, Hashable {
    public var providers: [ProviderInfo]

    public init(providers: [ProviderInfo]) {
        self.providers = providers
    }
}
