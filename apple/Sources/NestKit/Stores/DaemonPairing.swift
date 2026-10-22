import Foundation
import Observation

/// Pairs this Mac with a daemon on another machine (Settings > Devices > Pair a daemon):
/// finds Nest at the address (`GET /api/health`), redeems the one-time code the other
/// machine shows (`POST /api/pairing/redeem`), keeps the token in the Keychain, then adds
/// or updates the daemon in the list and selects it.
@MainActor @Observable
public final class DaemonPairing {
    /// Pairing codes: 8 characters without look-alikes (no 0, O, 1, I, L), as the PWA's.
    public static let codeLength = 8
    static let codeAlphabet = Set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")

    public var address: String {
        didSet {
            found = nil
            error = nil
        }
    }
    public var code = "" {
        didSet {
            let normalized = Self.normalize(code)
            if normalized != code {
                code = normalized
            }
        }
    }
    public var deviceName: String
    /// The machine Nest answered as at the address.
    public private(set) var found: String?
    public private(set) var error: String?
    public private(set) var isBusy = false

    @ObservationIgnored let daemons: DaemonList
    @ObservationIgnored let transport: any HTTPTransport
    @ObservationIgnored let now: @Sendable () -> Date

    public convenience init(daemons: DaemonList, deviceName: String, address: String = "") {
        self.init(
            daemons: daemons, deviceName: deviceName, address: address,
            transport: URLSessionTransport(), now: { Date() })
    }

    init(
        daemons: DaemonList, deviceName: String, address: String,
        transport: any HTTPTransport, now: @escaping @Sendable () -> Date
    ) {
        self.daemons = daemons
        self.deviceName = deviceName
        self.address = address
        self.transport = transport
        self.now = now
    }

    /// Upper case, only the code alphabet, at most `codeLength` characters.
    public static func normalize(_ text: String) -> String {
        String(text.uppercased().filter(codeAlphabet.contains).prefix(codeLength))
    }

    public var canPair: Bool {
        code.count == Self.codeLength
            && !address.trimmingCharacters(in: .whitespaces).isEmpty
            && !deviceName.trimmingCharacters(in: .whitespaces).isEmpty && !isBusy
    }

    /// "Found Nest on Mac mini", once found.
    public var foundText: String? {
        found.map { "Found Nest on \($0)" }
    }

    /// Looks for Nest at the address: `found` names the machine, or `error` says why not.
    public func check() async {
        _ = await locate()
    }

    /// Pairs and selects the daemon; nil with `error` set when it did not work.
    public func pair() async -> RemoteDaemon? {
        isBusy = true
        defer { isBusy = false }
        guard let (url, machine) = await locate() else { return nil }
        let client = APIClient(token: "", baseURL: url, transport: transport)
        let name = deviceName.trimmingCharacters(in: .whitespaces)
        let redeemed: RedeemedPairing
        do {
            redeemed = try await client.redeemPairing(code: code, deviceName: name)
        } catch {
            self.error = Self.refusal(error, host: DaemonAddress.display(url))
            return nil
        }
        let daemon = RemoteDaemon(
            machine: machine, baseURL: url, deviceID: redeemed.device.id,
            deviceName: redeemed.device.name, pairedAt: now())
        do {
            try KeychainTokenStore(baseURL: url, items: daemons.keychain).save(redeemed.token)
        } catch {
            self.error = "Could not keep the token: \(error.localizedDescription)"
            return nil
        }
        let saved = daemons.save(daemon)
        daemons.select(saved.id)
        return saved
    }

    private func locate() async -> (URL, String)? {
        error = nil
        let url: URL
        do {
            url = try DaemonAddress.parse(address)
        } catch {
            self.error = error.message
            return nil
        }
        let host = DaemonAddress.display(url)
        do {
            let health = try await APIClient(token: "", baseURL: url, transport: transport)
                .health()
            let machine = health.machine ?? host
            found = machine
            return (url, machine)
        } catch APIError.transport {
            error = "\(host) did not answer at this address"
        } catch {
            self.error = "This address is not a Nest daemon"
        }
        return nil
    }

    private static func refusal(_ error: any Error, host: String) -> String {
        guard let error = error as? APIError else { return error.localizedDescription }
        return switch error {
        case .invalidInput:
            "This code is wrong or has expired (codes last 5 minutes)"
        case .rateLimited(_, let seconds):
            "Too many tries, wait " + (seconds.map { "\($0) s" } ?? "a minute")
        case .transport:
            "\(host) did not answer at this address"
        default:
            error.message
        }
    }
}
