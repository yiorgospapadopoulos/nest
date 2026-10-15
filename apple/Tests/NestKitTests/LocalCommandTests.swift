import Foundation
import Testing

@testable import NestKit

private func model(_ value: String, _ name: String) -> ModelInfo {
    ModelInfo(
        value: value, displayName: name, description: "", effortLevels: [], supportsEffort: false)
}

@Suite struct LocalCommandTests {
    @Test func theInteractiveCommandsAreRunByNestNotSent() {
        #expect(LocalCommand("/model") == .model(nil))
        #expect(LocalCommand("  /model   opus  ") == .model("opus"))
        #expect(LocalCommand("/permissions") == .permissions)
        #expect(LocalCommand("/mcp\n") == .mcp)
        #expect(LocalCommand("/resume") == .resume(nil))
        #expect(LocalCommand("/resume login bug") == .resume("login bug"))
    }

    @Test func otherTextAndCommandsAreSentAsUsual() {
        #expect(LocalCommand("/compact") == nil)
        #expect(LocalCommand("/review the diff") == nil)
        #expect(LocalCommand("/models") == nil)
        #expect(LocalCommand("please run /model") == nil)
        #expect(LocalCommand("model") == nil)
        #expect(LocalCommand("") == nil)
        // These take no argument; with one they go to Claude Code as typed.
        #expect(LocalCommand("/mcp enable github") == nil)
        #expect(LocalCommand("/permissions add Bash") == nil)
        // Claude Code clears the context itself, inside the same chat (B31).
        #expect(LocalCommand("/clear") == nil)
        #expect(LocalCommand(named: "clear") == nil)
    }

    @Test func pickingOneFromTheListRunsIt() {
        #expect(LocalCommand(named: "model") == .model(nil))
        #expect(LocalCommand(named: "resume") == .resume(nil))
        #expect(LocalCommand(named: "mcp") == .mcp)
        #expect(LocalCommand(named: "review") == nil)
    }

    @Test func theSuggestionsOfferThemWithShortDescriptions() {
        let names = LocalCommand.commands.map(\.name)
        #expect(names == ["mcp", "model", "permissions", "resume"])
        #expect(LocalCommand.commands.allSatisfy { !($0.description ?? "").isEmpty })
        #expect(LocalCommand.commands.first { $0.name == "model" }?.argumentHint == "[model]")
    }

    @Test func nestsCommandsJoinClaudeCodesInNameOrderReplacingTheSameNames() {
        let known = [
            SlashCommand(name: "review", description: "Review"),
            SlashCommand(name: "clear", description: "Clear the context"),
            SlashCommand(name: "model", description: "Claude Code's model"),
            SlashCommand(name: "compact", description: "Compact"),
        ]
        let merged = LocalCommand.merged(known)
        #expect(
            merged.map(\.name) == [
                "clear", "compact", "mcp", "model", "permissions", "resume", "review",
            ])
        #expect(merged.first { $0.name == "clear" }?.description == "Clear the context")
        #expect(
            merged.first { $0.name == "model" }?.description
                == LocalCommand.commands.first { $0.name == "model" }?.description)
    }

    @Test func aModelIsFoundByItsValueOrNameExactlyThenByItsStart() {
        let models = [
            model("default", "Default (recommended)"), model("opus", "Opus"),
            model("sonnet[1m]", "Sonnet (1M context)"), model("haiku", "Haiku"),
        ]
        #expect(LocalCommand.model(named: "opus", in: models)?.value == "opus")
        #expect(LocalCommand.model(named: "HAIKU", in: models)?.value == "haiku")
        #expect(LocalCommand.model(named: "Sonnet (1M context)", in: models)?.value == "sonnet[1m]")
        #expect(LocalCommand.model(named: "son", in: models)?.value == "sonnet[1m]")
        #expect(LocalCommand.model(named: "gpt", in: models) == nil)
        // A name the list lacks is not guessed; Nest says it is unknown.
        #expect(LocalCommand.model(named: "claude-opus-5-5", in: models) == nil)
    }
}
