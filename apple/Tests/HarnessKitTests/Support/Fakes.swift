import Foundation
import Synchronization

@testable import HarnessKit

final class MemoryStore: KeyValueStore {
    var values: [String: String]

    init(_ values: [String: String] = [:]) {
        self.values = values
    }

    func string(forKey key: String) -> String? {
        values[key]
    }

    func set(_ value: String?, forKey key: String) {
        values[key] = value
    }
}

/// An event source the test feeds by hand.
final class ManualEventSource: EventSource {
    let continuation: AsyncThrowingStream<EventStreamUpdate, any Error>.Continuation
    private let stream: AsyncThrowingStream<EventStreamUpdate, any Error>

    init() {
        (stream, continuation) = AsyncThrowingStream.makeStream()
    }

    func updates() -> AsyncThrowingStream<EventStreamUpdate, any Error> {
        stream
    }
}

struct TokenStub: TokenStore {
    let token: String?

    func deviceToken() throws -> String? {
        token
    }
}
