import NestComputerCore
import Testing

// B159 R04: whoever launches the helper names the controller, so the helper accepts only
// the pid launchd reports for Nest's own daemon service.
@Suite struct DaemonJobTests {
    private func printed(pid: String?, environment: [String] = []) -> String {
        var lines = [
            "gui/501/com.nest.daemon = {",
            "\tactive count = 1",
            "\tstate = \(pid == nil ? "not running" : "running")",
            "\tenvironment = {",
        ]
        lines += environment.map { "\t\t\($0)" }
        lines += ["\t}", "\truns = 1"]
        if let pid { lines.append("\tpid = \(pid)") }
        lines += ["\tforks = 0", "}"]
        return lines.joined(separator: "\n")
    }

    @Test func onlyTheServicesRunningProcessMayControlTheHelper() throws {
        let output = printed(pid: "772")
        try DaemonJob.check(controller: 772, launchctlPrint: output)
        #expect(throws: HelperError.self) {
            try DaemonJob.check(controller: 4321, launchctlPrint: output)
        }
    }

    @Test func noRunningServiceMeansNoController() {
        #expect(throws: HelperError.self) {
            try DaemonJob.check(controller: 772, launchctlPrint: nil)
        }
        #expect(throws: HelperError.self) {
            try DaemonJob.check(controller: 772, launchctlPrint: self.printed(pid: nil))
        }
    }

    @Test func onlyTheJobsOwnPidLineCounts() {
        let nested = printed(pid: nil, environment: ["pid = 4321"])
        #expect(throws: HelperError.self) {
            try DaemonJob.check(controller: 4321, launchctlPrint: nested)
        }
        let twice = printed(pid: "772") + "\n\tpid = 4321"
        #expect(throws: HelperError.self) {
            try DaemonJob.check(controller: 4321, launchctlPrint: twice)
        }
    }
}
