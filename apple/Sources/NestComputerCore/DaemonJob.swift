/// Who may control the helper: only the running process of Nest's own daemon service. The
/// launcher names the controller, so any program could name itself (B159 R04); the helper
/// asks launchd instead, and taking this over means replacing Nest's service.
public enum DaemonJob {
    public static let label = "com.nest.daemon"
    public static let launchctl = "/bin/launchctl"

    /// `launchctl` arguments that describe the service in this user's GUI domain, where
    /// `nestd service install` loads it.
    public static func printArguments(uid: UInt32) -> [String] {
        ["print", "gui/\(uid)/\(label)"]
    }

    /// Throws unless `controller` is the service's running process. `output` is what
    /// `launchctl print` wrote, or nil when it failed (no such service).
    public static func check(controller: Int32, launchctlPrint output: String?)
        throws(HelperError)
    {
        guard let output else {
            throw HelperError(.noPermission, "\(label) is not loaded")
        }
        guard let pid = runningPID(in: output) else {
            throw HelperError(.noPermission, "\(label) is not running")
        }
        guard pid == controller else {
            throw HelperError(
                .noPermission, "pid \(controller) is not \(label)'s process (\(pid))")
        }
    }

    /// The job's own `pid = N` line, one tab in; deeper lines belong to its sections (its
    /// environment, say). More than one such line is not trusted.
    static func runningPID(in output: String) -> Int32? {
        let prefix = "\tpid = "
        let pids = output.split(separator: "\n", omittingEmptySubsequences: true)
            .filter { $0.hasPrefix(prefix) }
            .map { Int32($0.dropFirst(prefix.count)) }
        guard pids.count == 1, let pid = pids[0], pid > 1 else { return nil }
        return pid
    }
}
