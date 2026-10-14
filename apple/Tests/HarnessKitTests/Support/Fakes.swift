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

/// A Keychain whose token changes, as when the daemon stores a new one.
final class ChangingTokens: TokenStore {
    let token: Mutex<String?>
    /// Whether each read ran on the main thread, where a Keychain prompt would freeze it.
    let readsOnMain = Mutex<[Bool]>([])
    let failure = Mutex<TokenStoreError?>(nil)

    init(_ token: String?) {
        self.token = Mutex(token)
    }

    func deviceToken() throws -> String? {
        readsOnMain.withLock { $0.append(Thread.isMainThread) }
        if let failure = failure.withLock({ $0 }) {
            throw failure
        }
        return token.withLock { $0 }
    }
}
