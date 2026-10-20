/// Transcript entries that lay out together inside the transcript's lazy stack.
public struct TranscriptChunk: Sendable, Hashable, Identifiable {
    public let id: String
    public let entries: [TranscriptEntry]
}

/// The transcript in chunks for its lazy stack. A chunk lays out whole, so while scrolling
/// up the messages just above the view are already measured instead of estimated, and the
/// view does not jump as they appear. The latest entries are one chunk, so the end of the
/// chat, where most reading happens, is never estimated. Chunks count from the top: new
/// messages grow the tail and leave the earlier chunks as they were.
public enum TranscriptChunks {
    /// Entries in each older chunk.
    public static let size = 10
    /// The fewest entries in the latest chunk.
    public static let tail = 40
    public static let tailID = "transcript-tail"
    /// The most entries a chat lays out in full; a longer one keeps its oldest in lazy
    /// chunks, so a huge chat does not hold a view for every message.
    public static let most = 600

    public static func split(
        _ entries: [TranscriptEntry], size: Int = size, tail: Int = tail
    ) -> [TranscriptChunk] {
        let tailStart = max(entries.count - tail, 0) / size * size
        let older = stride(from: 0, to: tailStart, by: size).map { start in
            TranscriptChunk(
                id: "chunk-\(entries[start].id)", entries: Array(entries[start..<start + size]))
        }
        return older + [TranscriptChunk(id: tailID, entries: Array(entries[tailStart...]))]
    }

    /// The chunk holding an entry, or a tool call inside a group, to scroll to before the
    /// entry itself, which the lazy stack may not have laid out yet.
    public static func chunk(containing id: String, in chunks: [TranscriptChunk]) -> String? {
        chunks.first { chunk in
            chunk.entries.contains { $0.id == id }
                || TranscriptGrouping.group(containing: id, in: chunk.entries) != nil
        }?.id
    }
}
