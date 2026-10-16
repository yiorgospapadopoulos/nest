import Foundation
import Observation

/// What a work page shows, read-only (B46): a subagent's transcript, a pixie's calls in a
/// chat, or a team's (all its members' calls).
public enum WorkTarget: Sendable, Hashable {
    case subagent(session: String, toolUseID: String)
    case pixie(session: String, pixieID: String)
    case team(session: String, teamID: String, members: [String])

    /// The chat the work belongs to.
    public var session: String {
        switch self {
        case .subagent(let session, _), .pixie(let session, _), .team(let session, _, _):
            session
        }
    }
}

/// One call on a work page: what it was asked, the agent's own messages and its report.
public struct AgentWorkSection: Sendable, Hashable, Identifiable {
    /// The call's tool use id: an Agent call, or a SendMessage that continued one.
    public let id: String
    /// The pixie called; nil for a subagent.
    public let pixieID: String?
    public var state: PixieCallState
    /// It continued an earlier call's agent with its context.
    public let continued: Bool
    public let startedAt: Date?
    public let prompt: String?
    public var messages: [AgentWorkMessage]
    public var report: String?
    /// The Agent call whose id the agent's own messages carry: a continued agent's are its
    /// first call's.
    let parent: String

    /// The messages as transcript items, as a chat shows them.
    public var items: [TranscriptItem] { AgentWorkItems.items(messages) }
}

/// A subagent's own messages as transcript items: text, thinking and tool calls with
/// their results; the task list's bookkeeping is left out, as in a chat.
public enum AgentWorkItems {
    public static func items(_ messages: [AgentWorkMessage]) -> [TranscriptItem] {
        var items: [TranscriptItem] = []
        func append(_ id: String, _ content: TranscriptItem.Content, _ event: Int) {
            items.append(TranscriptItem(id: id, content: content, eventID: event))
        }
        for message in messages {
            for (index, block) in message.blocks.enumerated() {
                let id = "e\(message.eventID)-\(index)"
                switch block {
                case .text(let text):
                    append(id, .assistant(text, streaming: false), message.eventID)
                case .thinking(let text, let duration):
                    append(id, .thinking(text, durationMS: duration), message.eventID)
                case .toolUse(_, let name, _) where TranscriptStore.hiddenTools.contains(name):
                    break
                case .toolUse(let tool, let name, let input):
                    let call = ToolCall(id: tool, name: name, input: input, isError: false)
                    append(tool, .tool(call), message.eventID)
                case .toolResult(let tool, let content, let isError, let images):
                    guard let found = items.firstIndex(where: { $0.id == tool }),
                        case .tool(var call) = items[found].content
                    else { continue }
                    call.result = content
                    call.isError = isError
                    call.images = images
                    items[found].content = .tool(call)
                case .unknown:
                    break
                }
            }
        }
        return items
    }
}

/// A work page's calls, newest first, read once and then followed live: the agent's new
/// messages, its report and, for a pixie or team, a change of the chat's group.
@MainActor @Observable
public final class AgentWorkStore {
    public let target: WorkTarget
    public private(set) var sections: [AgentWorkSection] = []
    public private(set) var isLoaded = false
    /// Why the last read failed.
    public private(set) var loadError: String?

    let api: any NestAPI

    public init(target: WorkTarget, api: any NestAPI) {
        self.target = target
        self.api = api
    }

    public func load() async {
        do {
            switch target {
            case .subagent(let session, let tool):
                sections = [Self.section(try await api.agentTranscript(session, toolUseID: tool))]
            case .pixie(let session, let pixie):
                sections = Self.sections(try await api.pixieCallWork(session, pixie: pixie))
            case .team(let session, _, let members):
                var calls: [PixieCallWork] = []
                for member in members {
                    calls += try await api.pixieCallWork(session, pixie: member)
                }
                sections = Self.sections(calls)
            }
            loadError = nil
        } catch let error as APIError {
            loadError = error.message
        } catch {
            loadError = String(describing: error)
        }
        isLoaded = true
    }

    /// Applies a live event of the chat; a change of its group reads a pixie's or team's
    /// calls again, returning that read.
    @discardableResult
    public func receive(_ event: Event) -> Task<Void, Never>? {
        guard event.sessionID == target.session else { return nil }
        switch event.body {
        case .message(let message):
            if let parent = message.parentToolUseID {
                add(message.blocks, from: parent, event: event)
            } else {
                finish(with: message.blocks)
            }
        case .agentTask(let task) where task.phase == .finished:
            guard let index = sections.firstIndex(where: { $0.id == task.toolUseID }) else {
                return nil
            }
            sections[index].state = task.agentStatus == .done ? .done : .failed
            if let summary = task.summary {
                sections[index].report = summary
            }
        case .pixieGroup:
            if case .subagent = target {
                return nil
            }
            return Task { await load() }
        default:
            break
        }
        return nil
    }

    /// An agent's new message goes to the call running now among those whose agent's
    /// messages carry `parent`, else to the newest of them; once.
    private func add(_ blocks: [MessageBlock], from parent: String, event: Event) {
        guard let id = event.id else { return }
        let matching = sections.indices.filter { sections[$0].parent == parent }
        let running = matching.filter { sections[$0].state.isRunning }
        guard let index = (running + matching).first,
            !sections[index].messages.contains(where: { $0.eventID == id })
        else { return }
        sections[index].messages.append(
            AgentWorkMessage(eventID: id, ts: event.ts, blocks: blocks))
    }

    /// The main agent's results: an Agent call's is its subagent's report. A SendMessage
    /// answers at once, so a continued call's report waits for its task's end.
    private func finish(with blocks: [MessageBlock]) {
        for case .toolResult(let tool, let content, let isError, _) in blocks {
            guard let index = sections.firstIndex(where: { $0.id == tool && !$0.continued })
            else { continue }
            sections[index].report = SubagentReport.clean(content)
            sections[index].state = isError ? .failed : .done
        }
    }

    private static func section(_ work: AgentWork) -> AgentWorkSection {
        AgentWorkSection(
            id: work.toolUseID, pixieID: nil, state: work.report == nil ? .running : .done,
            continued: false, startedAt: nil, prompt: work.prompt, messages: work.messages,
            report: work.report, parent: work.toolUseID)
    }

    /// Newest first; a continued call's agent messages carry its agent's first call's id.
    private static func sections(_ works: [PixieCallWork]) -> [AgentWorkSection] {
        let sorted = works.sorted { ($0.call.startedAt, $0.id) > ($1.call.startedAt, $1.id) }
        var firsts: [String: String] = [:]
        for work in sorted where !work.call.continued {
            // Newest first: the oldest call of the agent is written last.
            if let agent = work.call.agentID {
                firsts[agent] = work.call.toolUseID
            }
        }
        return sorted.map { work in
            let call = work.call
            let first = call.continued ? call.agentID.flatMap { firsts[$0] } : nil
            return AgentWorkSection(
                id: call.toolUseID, pixieID: call.pixieID, state: call.state,
                continued: call.continued, startedAt: call.startedAt, prompt: work.prompt,
                messages: work.messages, report: work.report, parent: first ?? call.toolUseID)
        }
    }
}
