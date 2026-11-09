import AppKit
import ApplicationServices
import ImageIO
import NestComputerCore
import UniformTypeIdentifiers

/// Window screenshots through `/usr/sbin/screencapture -l`, which works for windows on
/// other desktops; ScreenCaptureKit failed on this Mac (B150 spike).
extension Desktop {
    func screenshot(window id: String) async throws(HelperError) -> [String: JSONValue] {
        let window = try window(id)
        guard let number = Screenshot.windowNumber(of: window) else {
            throw HelperError(.failed, "could not find window \(id) on screen")
        }
        // Tried before asking the preflight: macOS checks a nested app's Screen Recording
        // against Nest.app, the app it sits in (B150, D178).
        let raw: Data
        do {
            raw = try await Screenshot.capture(windowNumber: number)
        } catch  where !CGPreflightScreenCaptureAccess() {
            throw HelperError(.noPermission, "Nest Computer has no Screen Recording permission")
        }
        let (png, width, height) = try Screenshot.scaled(raw)
        return [
            "png": .string(png.base64EncodedString()), "width": .int(width),
            "height": .int(height),
        ]
    }
}

enum Screenshot {
    /// The window server's number for an AX window: the app's normal-layer window with the
    /// same frame, or its only one.
    static func windowNumber(of window: Desktop.Window) -> CGWindowID? {
        let list =
            CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID)
            as? [[String: Any]] ?? []
        let candidates = list.filter {
            ($0[kCGWindowOwnerPID as String] as? pid_t) == window.pid
                && ($0[kCGWindowLayer as String] as? Int) == 0
        }
        let frame = AX.frame(window.element)
        let title = AX.string(window.element, kAXTitleAttribute)
        let sameFrame = candidates.filter { info in
            guard let frame, let bounds = info[kCGWindowBounds as String] as? NSDictionary,
                let rect = CGRect(dictionaryRepresentation: bounds)
            else { return false }
            return abs(rect.minX - frame.x) < 1 && abs(rect.minY - frame.y) < 1
                && abs(rect.width - frame.width) < 1 && abs(rect.height - frame.height) < 1
        }
        let match =
            sameFrame.first { ($0[kCGWindowName as String] as? String) == title }
            ?? sameFrame.first ?? (candidates.count == 1 ? candidates.first : nil)
        return (match?[kCGWindowNumber as String] as? NSNumber)?.uint32Value
    }

    static func capture(windowNumber: CGWindowID) async throws(HelperError) -> Data {
        let folder = FileManager.default.temporaryDirectory
        let file = folder.appending(path: "nest-computer-\(UUID().uuidString).png")
        defer { try? FileManager.default.removeItem(at: file) }
        let process = Process()
        process.executableURL = URL(filePath: "/usr/sbin/screencapture")
        process.arguments = ["-x", "-o", "-l", String(windowNumber), file.path]
        let status: Int32
        do {
            status = try await run(process, timeout: .seconds(10))
        } catch {
            throw HelperError(.failed, "screencapture did not run: \(error.localizedDescription)")
        }
        guard status == 0, let data = try? Data(contentsOf: file), !data.isEmpty else {
            throw HelperError(.failed, "screencapture failed (exit \(status))")
        }
        return data
    }

    /// The PNG scaled so its long side is at most 1280 pixels.
    static func scaled(_ data: Data) throws(HelperError) -> (Data, Int, Int) {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
            let image = CGImageSourceCreateImageAtIndex(source, 0, nil)
        else { throw HelperError(.failed, "the screenshot is not an image") }
        let size = fittedSize(width: image.width, height: image.height)
        if size.width == image.width && size.height == image.height {
            return (data, image.width, image.height)
        }
        guard
            let context = CGContext(
                data: nil, width: size.width, height: size.height, bitsPerComponent: 8,
                bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
        else { throw HelperError(.failed, "could not scale the screenshot") }
        context.interpolationQuality = .high
        context.draw(image, in: CGRect(x: 0, y: 0, width: size.width, height: size.height))
        let output = NSMutableData()
        guard let scaled = context.makeImage(),
            let destination = CGImageDestinationCreateWithData(
                output, UTType.png.identifier as CFString, 1, nil)
        else { throw HelperError(.failed, "could not scale the screenshot") }
        CGImageDestinationAddImage(destination, scaled, nil)
        guard CGImageDestinationFinalize(destination) else {
            throw HelperError(.failed, "could not encode the screenshot")
        }
        return (output as Data, size.width, size.height)
    }

    /// Runs a process and waits for it, stopping it after `timeout`.
    private static func run(_ process: Process, timeout: Duration) async throws -> Int32 {
        let (exits, exit) = AsyncStream<Int32>.makeStream()
        process.terminationHandler = { finished in
            exit.yield(finished.terminationStatus)
            exit.finish()
        }
        try process.run()
        let pid = process.processIdentifier
        let watchdog = Task {
            try await Task.sleep(for: timeout)
            kill(pid, SIGKILL)
        }
        defer { watchdog.cancel() }
        for await status in exits { return status }
        return -1
    }
}
