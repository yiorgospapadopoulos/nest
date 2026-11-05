import Foundation
import Testing

@testable import NestKit

/// What the composer reads of a chat now that the transcript is a page (D150): up arrow, Esc
/// Esc and dictation's vocabulary.
@MainActor
@Suite struct ChatHistoryTests {
    private func user(_ id: Int, _ text: String, extra: String = "") -> Event {
        let body = try! JSONEncoder().encode(text)
        return Fixture.event(
            EventType.sessionUserMessage,
            #"{"text": \#(String(decoding: body, as: UTF8.self)), "attachments": []\#(extra)}"#,
            id: id, session: "c")
    }

    private func said(_ id: Int, _ blocks: String) -> Event {
        Fixture.event(
            EventType.sessionMessage, #"{"blocks": [\#(blocks)], "parent_tool_use_id": null}"#,
            id: id, session: "c")
    }

    @Test func theLatestOwnMessageIsWhatUpArrowAndEscEscFind() {
        let history = ChatHistory(events: [
            user(1, "first"), said(2, #"{"type": "text", "text": "ok"}"#), user(3, "second"),
        ])
        #expect(history.lastText == "second")
        #expect(history.lastMessage == 3)
    }

    @Test func messagesNestSentAreNotTheUsers() {
        let history = ChatHistory(events: [
            user(1, "mine"), user(2, "a pixie's report", extra: #", "origin": "report_back""#),
            user(3, "go on", extra: #", "origin": "autopilot""#),
        ])
        #expect(history.lastText == "mine")
        #expect(history.lastMessage == 1)
    }

    @Test func aChatWithoutMessagesFindsNothing() {
        #expect(ChatHistory().lastText == nil)
        #expect(ChatHistory().lastMessage == nil)
    }

    @Test func filesComeNewestFirstAndSubagentsDoNotCount() {
        let tool =
            #"{"type": "tool_use", "id": "t", "name": "Read", "input": {"file_path": "/a/Old.swift"}}"#
        let inside = Fixture.event(
            EventType.sessionMessage,
            #"{"blocks": [{"type": "text", "text": "Hidden.swift"}], "parent_tool_use_id": "x"}"#,
            id: 3, session: "c")
        let history = ChatHistory(events: [
            said(1, tool), user(2, "see New.swift"), inside,
        ])
        #expect(history.files == ["New.swift", "Old.swift"])
        #expect(
            DictationVocabulary.terms(repo: nil, branch: nil, files: history.files).prefix(4) == [
                "New.swift", "New", "Old.swift", "Old",
            ])
    }
}
