import Foundation
import Testing

@testable import NestKit

@Suite struct DaemonLocationTests {
    let home = URL(filePath: "/Users/me")

    @Test func withoutVariablesTheDefaultDaemonIsUsed() {
        for environment in [[:], ["NEST_DAEMON_URL": "", "NEST_DATA_DIR": ""]] {
            let location = DaemonLocation(environment: environment, home: home)
            #expect(location.baseURL == APIClient.defaultBaseURL)
            #expect(
                location.dataFolder.path
                    == "/Users/me/Library/Application Support/nest")
        }
    }

    @Test func aLoopbackDaemonURLIsUsed() {
        for text in [
            "http://127.0.0.1:8812", "https://127.0.0.1:8812/", "http://localhost:8812",
            "http://[::1]:8812",
        ] {
            let location = DaemonLocation(environment: ["NEST_DAEMON_URL": text], home: home)
            #expect(location.baseURL == URL(string: text)!, "\(text)")
        }
    }

    /// The app only ever talks to this Mac: anything else falls back to the default.
    @Test func aDaemonURLThatIsNotPlainLoopbackIsIgnored() {
        for text in [
            "http://example.com:8812", "http://192.168.1.2:8812", "ftp://127.0.0.1:8812",
            "ws://127.0.0.1:8812", "127.0.0.1:8812", "http://user:pw@127.0.0.1:8812",
            "http://127.0.0.1:8812/api", "http://127.0.0.1:8812/?a=1",
            "http://127.0.0.1:8812/#x", "http://127.0.0.1.example.com", "not a url",
        ] {
            let location = DaemonLocation(environment: ["NEST_DAEMON_URL": text], home: home)
            #expect(location.baseURL == APIClient.defaultBaseURL, "\(text)")
        }
    }

    @Test func theDataFolderFollowsTheDaemonsVariable() {
        let location = DaemonLocation(environment: ["NEST_DATA_DIR": "/tmp/nest-test"], home: home)
        #expect(location.dataFolder.path == "/tmp/nest-test")
        #expect(location.baseURL == APIClient.defaultBaseURL)
    }

    @Test func theTokenStoreAsksTheSocketInTheDataFolder() {
        let store = SocketTokenStore(dataFolder: URL(filePath: "/tmp/nest-test"))
        #expect(store.path == "/tmp/nest-test/token.sock")
        #expect(
            SocketTokenStore().path
                == FileManager.default.homeDirectoryForCurrentUser
                .appending(path: "Library/Application Support/nest/token.sock").path)
    }
}
