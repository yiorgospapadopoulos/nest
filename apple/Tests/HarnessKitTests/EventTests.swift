import Foundation
import Testing

@testable import HarnessKit

@Suite struct EventDecodingTests {
    @Test func decodesAPersistedSessionHistory() {
        let events = Fixture.events
        #expect(events.map(\.id) == Array(10...21))
        #expect(events.allSatisfy { $0.sessionID == "5b8f3c2a9d1e4f60a7b8c9d0e1f2a3b4" })
        #expect(events[0].ts == Date(timeIntervalSince1970: 1_791_277_950.5))
    }

    @Test func typedBodiesOfTheHistory() throws {
        let bodies = Fixture.events.map(\.body)

        guard case .sessionCreated(let session) = bodies[0] else { throw Unexpected(bodies[0]) }
        #expect(session.title == "Validate contact form with zod")
        #expect(bodies[1] == .sessionState(.starting, error: nil))
        guard case .userMessage(let message) = bodies[2] else { throw Unexpected(bodies[2]) }
        #expect(message.attachments.map(\.mediaType) == ["image/png"])
        #expect(message.attachments[0].createdAt == nil)
        guard case .message(let agentMessage) = bodies[4] else { throw Unexpected(bodies[4]) }
        #expect(
            agentMessage.blocks == [
                .thinking("The route posts JSON.", durationMS: nil),
                .text("I'll read the route first."),
                .toolUse(
                    id: "toolu_01", name: "Read",
                    input: .object(["file_path": .string("app/api/contact/route.ts")])),
            ])
        #expect(agentMessage.parentToolUseID == nil)
        guard case .message(let result) = bodies[5] else { throw Unexpected(bodies[5]) }
        #expect(
            result.blocks == [
                .toolResult(
                    toolUseID: "toolu_01", content: "export async function POST() {}",
                    isError: false)
            ])
        guard case .approvalCreated(let created) = bodies[7] else { throw Unexpected(bodies[7]) }
        #expect(created.kind == .permission)
        guard case .approvalResolved(let resolved) = bodies[8] else { throw Unexpected(bodies[8]) }
        #expect(resolved.status == .resolved)
        guard case .result(let turn) = bodies[10] else { throw Unexpected(bodies[10]) }
        #expect(turn.durationMS == 41_250)
        #expect(turn.numTurns == 6)
        #expect(turn.costUSD == nil)
        #expect(!turn.isError)
        #expect(turn.subtype == "success")
        #expect(turn.errors.isEmpty)
    }

    @Test func typedBodiesOfLiveEvents() throws {
        #expect(
            Fixture.event(EventType.sessionDelta, #"{"text": "Hel"}"#, id: nil).body
                == .delta("Hel"))
        #expect(
            Fixture.event(EventType.sessionThinking, #"{"active": true}"#, id: nil).body
                == .thinking(active: true))
        #expect(
            Fixture.event(EventType.sessionThinking, #"{"active": false}"#, id: nil).body
                == .thinking(active: false))
        // Anything but true ends it, as in the PWA.
        #expect(
            Fixture.event(EventType.sessionThinking, #"{}"#, id: nil).body
                == .thinking(active: false))
        #expect(
            Fixture.event(EventType.sessionState, #"{"state": "failed", "error": "boom"}"#).body
                == .sessionState(.failed, error: "boom"))
        #expect(
            Fixture.event(EventType.sessionDeleted, #"{"session_id": "s9"}"#, session: nil).body
                == .sessionDeleted(sessionID: "s9"))
        #expect(
            Fixture.event(EventType.gitFailed, #"{"step": "push", "stderr": "denied"}"#).body
                == .gitFailed(step: "push", stderr: "denied"))
        #expect(
            Fixture.event(EventType.gitCommitted, #"{"sha": "abc"}"#).body
                == .gitCommitted(sha: "abc"))
        #expect(
            Fixture.event(EventType.gitPushed, #"{"remote": "origin", "branch": "b"}"#).body
                == .gitPushed(branch: "b"))
        #expect(
            Fixture.event(EventType.prOpened, #"{"url": "https://example.com/pr/1"}"#).body
                == .prOpened(url: "https://example.com/pr/1"))
        let tasks = Fixture.event(
            EventType.sessionTasks,
            #"{"tasks": [{"id": "1", "subject": "S", "description": null, "active_form": null, "status": "pending"}]}"#
        )
        guard case .tasks(let list) = tasks.body else { throw Unexpected(tasks.body) }
        #expect(list.map(\.subject) == ["S"])
        let agents = Fixture.event(EventType.sessionAgents, #"{"agents": []}"#, id: nil)
        #expect(agents.body == .agents([], background: nil))
        let notice = Fixture.event(
            EventType.notify,
            #"{"kind": "review_ready", "session_id": "s1", "repo": "todo-ui", "title": "T", "text": "3 files changed"}"#
        )
        #expect(
            notice.body
                == .notify(
                    Notice(
                        kind: .reviewReady, sessionID: "s1", repo: "todo-ui", title: "T",
                        text: "3 files changed")))
        let usage = Fixture.event(
            EventType.usageUpdated,
            #"{"five_hour": {"utilization": 0.5, "resets_at": null}, "seven_day": null}"#,
            session: nil)
        #expect(
            usage.body
                == .usageUpdated(
                    UsageLimits(
                        fiveHour: LimitWindow(utilization: 0.5, resetsAt: nil, updatedAt: nil),
                        sevenDay: nil)))
        let connectors = Fixture.event(
            EventType.connectorsUpdated, "{\"connectors\": \(Fixture.text("connectors"))}",
            session: nil)
        #expect(connectors.body == .connectorsUpdated(Fixture.connectors))
        let updated = Fixture.event(
            EventType.sessionUpdated,
            "{\"changes\": {\"pinned\": false}, \"session\": \(Fixture.json(Fixture.sessions[1]))}")
        guard case .sessionUpdated(let session) = updated.body else {
            throw Unexpected(updated.body)
        }
        #expect(session.id == Fixture.sessions[1].id)
        #expect(session.title == "Dark mode contrast")
    }

    @Test func gitViolationAndWorkspaceEvents() {
        #expect(
            Fixture.event(
                EventType.sessionGitViolation,
                #"{"changes": [{"ref": "HEAD", "before": "a", "after": "b"}]}"#
            ).body == .gitViolation)
        #expect(
            Fixture.event(
                EventType.sessionWorkspace,
                #"{"path": "/w/s1", "branch": "agent/s1", "base_ref": "abc", "linked": [".env"], "missing": [], "existing": []}"#
            ).body
                == .workspace(SessionWorkspace(path: "/w/s1", branch: "agent/s1", baseRef: "abc")))
        #expect(
            Fixture.event(
                EventType.sessionWorkspace, #"{"path": "/w/s1", "branch": null, "base_ref": null}"#
            ).body == .workspace(SessionWorkspace(path: "/w/s1", branch: nil, baseRef: nil)))
        #expect(Fixture.event(EventType.sessionWorkspace, #"{"branch": "b"}"#).body == .other)
    }

    @Test func unknownTypesAndBadPayloadsReadAsOther() {
        #expect(Fixture.event("daemon.started", #"{"version": "0.1.0"}"#).body == .other)
        #expect(Fixture.event(EventType.sessionDelta, #"{"text": 3}"#).body == .other)
        #expect(Fixture.event(EventType.sessionState, #"{}"#).body == .other)
    }

    @Test func unknownBlocksAndMissingErrorFlags() throws {
        let event = Fixture.event(
            EventType.sessionMessage,
            #"{"blocks": [{"type": "image"}, {"type": "tool_result", "tool_use_id": "t", "content": "x"}], "parent_tool_use_id": "toolu_9"}"#
        )
        guard case .message(let message) = event.body else { throw Unexpected(event.body) }
        #expect(
            message.blocks == [.unknown, .toolResult(toolUseID: "t", content: "x", isError: false)])
        #expect(message.parentToolUseID == "toolu_9")
    }
}

struct Unexpected: Error {
    init(_ value: Any) {
        description = "\(value)"
    }

    let description: String
}
