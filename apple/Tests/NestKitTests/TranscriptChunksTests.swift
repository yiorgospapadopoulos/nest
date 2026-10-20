import Testing

@testable import NestKit

@Suite struct TranscriptChunksTests {
    private func entries(_ count: Int) -> [TranscriptEntry] {
        (0..<count).map { index in
            .item(
                TranscriptItem(
                    id: "m\(index)", content: .assistant("text", streaming: false), eventID: index))
        }
    }

    private func ids(_ chunk: TranscriptChunk) -> [String] { chunk.entries.map(\.id) }

    @Test func aShortTranscriptIsOneTailLaidOutWhole() {
        let chunks = TranscriptChunks.split(entries(40), size: 10, tail: 40)
        #expect(chunks.map(\.id) == [TranscriptChunks.tailID])
        #expect(chunks[0].entries.count == 40)
        #expect(
            TranscriptChunks.split([], size: 10, tail: 40).map(\.id) == [TranscriptChunks.tailID])
    }

    @Test func olderEntriesComeInChunksCountedFromTheTop() {
        let chunks = TranscriptChunks.split(entries(57), size: 10, tail: 40)
        #expect(chunks.map(\.id) == ["chunk-m0", TranscriptChunks.tailID])
        #expect(ids(chunks[0]) == (0..<10).map { "m\($0)" })
        // The tail keeps at least `tail` entries, and fewer than `tail + size`.
        #expect(chunks[1].entries.count == 47)
        #expect(chunks.flatMap(ids) == entries(57).map(\.id))
    }

    @Test func newMessagesLeaveEarlierChunksAsTheyWere() {
        let before = TranscriptChunks.split(entries(59), size: 10, tail: 40)
        let after = TranscriptChunks.split(entries(60), size: 10, tail: 40)
        #expect(before.map(\.id) == ["chunk-m0", TranscriptChunks.tailID])
        #expect(after.map(\.id) == ["chunk-m0", "chunk-m10", TranscriptChunks.tailID])
        #expect(after[0] == before[0])
        #expect(after[2].entries.count == 40)
    }

    @Test func findsTheChunkHoldingAnEntryOrAToolCallInsideAGroup() {
        let calls = ["t1", "t2"].map { id in
            TranscriptItem(
                id: id,
                content: .tool(
                    ToolCall(
                        id: id, name: "Read", input: .object([:]), result: "ok", isError: false)),
                eventID: 1)
        }
        let group = TranscriptEntry.tools(
            ToolGroup(id: "g1", items: calls, isRunning: false, background: []))
        let chunks = TranscriptChunks.split(
            [group] + entries(12), size: 10, tail: 3)
        #expect(TranscriptChunks.chunk(containing: "m0", in: chunks) == "chunk-g1")
        #expect(TranscriptChunks.chunk(containing: "t2", in: chunks) == "chunk-g1")
        #expect(TranscriptChunks.chunk(containing: "g1", in: chunks) == "chunk-g1")
        #expect(TranscriptChunks.chunk(containing: "m11", in: chunks) == TranscriptChunks.tailID)
        #expect(TranscriptChunks.chunk(containing: "nope", in: chunks) == nil)
    }
}
