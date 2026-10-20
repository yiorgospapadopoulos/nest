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

    public var id: String { name }

    public init(
        name: String, displayName: String, signedIn: Bool? = nil, signInHint: String? = nil,
        account: ClaudeAccount? = nil, unsupported: Set<ProviderFeature> = []
    ) {
        self.name = name
        self.displayName = displayName
        self.signedIn = signedIn
        self.signInHint = signInHint
        self.account = account
        self.unsupported = unsupported
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
    }

    enum CodingKeys: String, CodingKey {
        case name, account, unsupported
        case displayName = "display_name"
        case signedIn = "signed_in"
        case signInHint = "sign_in_hint"
    }
}

/// `GET /api/providers`: the default engine first.
public struct ProviderList: Decodable, Sendable, Hashable {
    public var providers: [ProviderInfo]

    public init(providers: [ProviderInfo]) {
        self.providers = providers
    }
}
