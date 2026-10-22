import Foundation
import Observation

/// Paired devices and the one-time code that pairs a new one.
@MainActor @Observable
public final class DevicesStore {
    /// Devices that are not revoked; this Mac first.
    public private(set) var devices: [Device] = []
    public private(set) var pairingCode: PairingCode?
    public private(set) var revoking: Set<String> = []
    public private(set) var isCreatingCode = false
    /// How many devices get push notifications; nil until read (B81).
    public private(set) var pushDevices: Int?

    let api: any NestAPI
    let now: @Sendable () -> Date
    /// The daemon the list is of: This Mac's, or a remote's (B105).
    let link: DaemonLink

    public init(
        api: any NestAPI, now: @escaping @Sendable () -> Date = { Date() },
        link: DaemonLink = DaemonLink()
    ) {
        self.api = api
        self.now = now
        self.link = link
    }

    /// This Mac's device on a remote daemon; nil on This Mac's, where it is the local one.
    public var thisMacDevice: String? { link.remote?.deviceID }

    /// "Paired with This Mac", or with the remote machine.
    public var pairedWith: String { "Paired with \(link.machineName)" }

    /// A remote daemon's own device goes by its machine's name.
    public func title(_ device: Device) -> String {
        link.isRemote && device.isLocal ? link.machineName : device.name
    }

    /// "This Mac" for this Mac's device, "The daemon's machine" for a remote's own, else
    /// when it was last seen.
    public func detail(_ device: Device) -> String {
        if link.isRemote && device.isLocal {
            return "The daemon's machine"
        }
        if device.isLocal || device.id == thisMacDevice {
            return DaemonText.thisMac
        }
        return lastSeenText(device)
    }

    public func load() async throws {
        let all = try await api.devices().filter { $0.revokedAt == nil }
        devices = all.filter(\.isLocal) + all.filter { !$0.isLocal }
    }

    public func loadPushStatus() async throws {
        pushDevices = try await api.pushStatus().devices
    }

    /// "On for 2 devices", "Off" with none, "-" before it was read.
    public var pushText: String {
        switch pushDevices {
        case nil: "-"
        case 0: "Off"
        case 1: "On for 1 device"
        case let count?: "On for \(count) devices"
        }
    }

    /// Revokes a device; its token stops working at once.
    public func revoke(_ device: Device) async throws {
        revoking.insert(device.id)
        defer { revoking.remove(device.id) }
        try await api.revokeDevice(device.id)
        devices.removeAll { $0.id == device.id }
    }

    /// A fresh one-time code; it replaces any earlier one.
    public func createPairingCode() async throws {
        isCreatingCode = true
        defer { isCreatingCode = false }
        pairingCode = try await api.createPairingCode()
    }

    public func clearPairingCode() {
        pairingCode = nil
    }

    /// Seconds until the code expires; zero once it has.
    public func secondsLeft(at date: Date) -> Int {
        guard let code = pairingCode else { return 0 }
        return max(0, Int(code.expiresAt.timeIntervalSince(date).rounded(.up)))
    }

    /// "Expires in 4:59", or "Expired".
    public func expiryText(at date: Date) -> String {
        let seconds = secondsLeft(at: date)
        guard seconds > 0 else { return "Expired" }
        return "Expires in \(seconds / 60):" + String(format: "%02d", seconds % 60)
    }

    /// This Mac's own token cannot be revoked from here, nor the daemon's own on a remote:
    /// either would lock the app out.
    public func canRevoke(_ device: Device) -> Bool {
        !device.isLocal && device.id != thisMacDevice
    }

    /// "This device", "Last seen 5m ago", "Last seen now" or "Not seen yet".
    public func lastSeenText(_ device: Device) -> String {
        if device.isLocal {
            return "This device"
        }
        guard let seen = device.lastSeenAt else { return "Not seen yet" }
        let elapsed = Elapsed.short(from: seen, to: now())
        return elapsed == "now" ? "Last seen now" : "Last seen \(elapsed) ago"
    }
}
