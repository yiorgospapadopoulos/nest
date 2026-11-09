import Foundation
import NestComputerCore

/// Answers request lines, one at a time.
@MainActor
final class Dispatcher {
    private let desktop = Desktop()
    private let version =
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"

    func reply(to line: Data) async -> Reply {
        switch decodeRequest(line) {
        case .failure(let failure):
            return .failure(id: failure.id, error: failure.error)
        case .success(let request):
            do throws(HelperError) {
                let command = try Command(request)
                return .success(id: request.id, result: try await run(command))
            } catch {
                return .failure(id: request.id, error: error)
            }
        }
    }

    private func run(_ command: Command) async throws(HelperError) -> [String: JSONValue] {
        if command.needsAccessibility { try Permissions.requireAccessibility() }
        switch command {
        case .hello:
            return [
                "version": .string(version), "accessibility": .bool(Permissions.accessibility),
                "screen_recording": .bool(Permissions.screenRecording),
            ]
        case .askPermission(let permission):
            return ["granted": .bool(Permissions.ask(permission))]
        case .launch(let bundleID):
            return ["pid": .int(Int(try await desktop.launch(bundleID: bundleID)))]
        case .apps:
            return ["apps": .array(desktop.apps())]
        case .tree(let window, let maxNodes, let maxDepth):
            return try await desktop.tree(window: window, maxNodes: maxNodes, maxDepth: maxDepth)
        case .menu(let pid, let path):
            return ["new_windows": .array(try await desktop.menu(pid: pid, path: path))]
        case .press(let element, let action):
            try await desktop.press(element: element, action: action)
        case .setValue(let element, let text):
            try await desktop.setValue(element: element, text: text)
        case .focus(let element):
            try await desktop.focus(element: element)
        case .type(let pid, let text):
            try await desktop.type(pid: pid, text: text)
        case .key(let pid, let code, let modifiers):
            await desktop.key(pid: pid, code: code, modifiers: modifiers)
        case .scroll(let target, let direction, let amount):
            try await desktop.scroll(target: target, direction: direction, amount: amount)
        case .click(let window, let x, let y):
            try await desktop.click(window: window, x: x, y: y)
        case .front(let pid, let window):
            try desktop.front(pid: pid, window: window)
        case .screenshot(let window):
            return try await desktop.screenshot(window: window)
        }
        return [:]
    }
}
