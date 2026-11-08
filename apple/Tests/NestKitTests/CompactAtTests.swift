import Foundation
import Testing

@testable import NestKit

/// How full a chat's context gets before its engine compacts it (B146): what the menus
/// offer, what updates send and what older daemons leave out.
@Suite struct CompactAtTests {
    @Test func offersAutoAndTheFiveSizes() {
        #expect(CompactAt.choices.map(\.label) == ["Auto", "100k", "300k", "400k", "700k", "1M"])
        #expect(CompactAt.choices.dropFirst().compactMap(\.tokens).last == 1_000_000)
    }

    @Test func updatesSendAutoAsAWordAndASizeAsANumber() {
        #expect(
            Fixture.json(UpdateSessionRequest(compactAt: .auto)) == #"{"compact_at":"auto"}"#)
        #expect(
            Fixture.json(UpdateSessionRequest(compactAt: .tokens(300_000)))
                == #"{"compact_at":300000}"#)
        #expect(Fixture.json(UpdateSessionRequest(effort: .high)) == #"{"effort":"high"}"#)
        #expect(Fixture.json(UpdatePixieRequest(compactAt: .auto)) == #"{"compact_at":"auto"}"#)
        #expect(
            Fixture.json(UpdatePixieRequest(compactAt: .tokens(700_000)))
                == #"{"compact_at":700000}"#)
    }

    @Test func sessionsAndPixiesReadTheSizeAndOlderDaemonsReadAsAuto() throws {
        #expect(Fixture.decode(Session.self, "session_detail").compactAt == nil)
        let session = try Self.adding(#""compact_at": 100000"#, to: "session_detail")
        #expect(try NestJSON.decoder.decode(Session.self, from: session).compactAt == 100_000)

        #expect(Fixture.decode(Pixie.self, "pixie").compactAt == nil)
        let pixie = try Self.adding(#""compact_at": 1000000"#, to: "pixie")
        let decoded = try NestJSON.decoder.decode(Pixie.self, from: pixie)
        #expect(CompactAt(decoded.compactAt) == .tokens(1_000_000))
        // The pixie shows its new size while the change saves, and Auto clears it.
        #expect(decoded.applying(UpdatePixieRequest(compactAt: .auto)).compactAt == nil)
        #expect(decoded.applying(UpdatePixieRequest(name: "N")).compactAt == 1_000_000)
    }

    @MainActor @Test func anEngineThatCannotChooseHidesTheChoice() async {
        let list = Fixture.decode(
            ProviderList.self,
            json: """
                {"providers": [
                  {"name": "claude", "display_name": "Claude", "unsupported": []},
                  {"name": "gemini", "display_name": "Gemini",
                   "unsupported": ["compact_window"]}
                ]}
                """)
        #expect(list.providers[1].unsupported == [.compactWindow])
        let api = FakeAPI()
        api.set { $0.providers = list.providers }
        let store = ProvidersStore(api: api)
        await store.load()
        #expect(store.supports(.compactWindow, on: "claude"))
        #expect(!store.supports(.compactWindow, on: "gemini"))
    }

    /// The fixture's JSON object with one more field.
    private static func adding(_ field: String, to fixture: String) throws -> Data {
        var text = Fixture.text(fixture).trimmingCharacters(in: .whitespacesAndNewlines)
        text.removeFirst()
        return Data(("{" + field + "," + text).utf8)
    }
}
