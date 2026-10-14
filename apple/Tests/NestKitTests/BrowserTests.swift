import Foundation
import Testing

@testable import NestKit

@Suite struct BrowserAddressTests {
    @Test(arguments: [
        ("3000", "http://localhost:3000"),
        (":5173", "http://localhost:5173"),
        ("localhost", "http://localhost"),
        ("localhost:3000/about", "http://localhost:3000/about"),
        ("LOCALHOST:8000", "http://LOCALHOST:8000"),
        ("127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("0.0.0.0:4321", "http://0.0.0.0:4321"),
        ("[::1]:3000", "http://[::1]:3000"),
        ("devbox:8080/x", "http://devbox:8080/x"),
        ("example.com", "https://example.com"),
        ("github.com/me/todo-ui?tab=pulls", "https://github.com/me/todo-ui?tab=pulls"),
        ("http://example.com/a", "http://example.com/a"),
        ("https://localhost:8443", "https://localhost:8443"),
        ("about:blank", "about:blank"),
        ("  docs.swift.org  ", "https://docs.swift.org"),
    ])
    func addressesOpen(_ input: String, _ expected: String) {
        #expect(BrowserAddress.url(from: input)?.absoluteString == expected)
    }

    @Test(arguments: ["swift testing", "readme", "70000", "host:notaport"])
    func otherTextIsAWebSearch(_ input: String) throws {
        let url = try #require(BrowserAddress.url(from: input))
        let components = try #require(URLComponents(url: url, resolvingAgainstBaseURL: false))
        #expect(components.host == "duckduckgo.com")
        #expect(components.queryItems == [URLQueryItem(name: "q", value: input)])
    }

    @Test func blankOpensNothing() {
        #expect(BrowserAddress.url(from: "  ") == nil)
    }

    @Test func hostsAndPorts() {
        #expect(BrowserAddress.host(of: "[::1]") == ("[::1]", false))
        #expect(BrowserAddress.host(of: "[::1]:80/a") == ("[::1]", true))
        #expect(BrowserAddress.host(of: "a.b:12#x") == ("a.b", true))
        #expect(BrowserAddress.host(of: "a.b?q=1:2") == ("a.b", false))
    }
}

@Suite struct LocalServersTests {
    static let output = """
        COMMAND     PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
        ControlCe   601 me    10u  IPv4 0x1234567890abcdef      0t0  TCP *:7000 (LISTEN)
        ControlCe   601 me    11u  IPv6 0x1234567890abcdee      0t0  TCP *:7000 (LISTEN)
        rapportd    612 me     8u  IPv4 0x1234567890abcded      0t0  TCP *:49152 (LISTEN)
        node      12345 me    23u  IPv6 0x1234567890abcdec      0t0  TCP [::1]:5173 (LISTEN)
        node      12345 me    24u  IPv4 0x1234567890abcdeb      0t0  TCP 127.0.0.1:5173 (LISTEN)
        Python    23456 me     5u  IPv4 0x1234567890abcdea      0t0  TCP 127.0.0.1:8765 (LISTEN)
        Python    23457 me     6u  IPv4 0x1234567890abcde9      0t0  TCP *:8000 (LISTEN)
        Google\\x20C 3456 me    40u  IPv4 0x1234567890abcde8      0t0  TCP 127.0.0.1:9222 (LISTEN)
        tailscale  777 me     9u  IPv4 0x1234567890abcde7      0t0  TCP 100.64.0.1:443 (LISTEN)
        ruby      4567 me     9u  IPv4 0x1234567890abcde6      0t0  TCP 0.0.0.0:3000 (LISTEN)
        odd       4568 me     9u  IPv4 0x1234567890abcde5      0t0  TCP *:http (LISTEN)
        short line
        """

    @Test func listsDevServersOncePerPort() {
        let servers = LocalServers.parse(Self.output)
        #expect(servers.map(\.port) == [3000, 5173, 8000, 9222])
        #expect(servers.map(\.process) == ["ruby", "node", "Python", "Google C"])
        #expect(servers[1].url.absoluteString == "http://localhost:5173")
        #expect(servers[1].id == 5173)
    }

    @Test func nothingListeningIsAnEmptyList() {
        #expect(LocalServers.parse("").isEmpty)
    }

    @Test func scansWithLsof() async {
        let runner = FakeRunner([CommandOutput(status: 0, output: Self.output)])
        let servers = await LocalServers.scan(runner: runner)
        #expect(servers.count == 4)
        #expect(runner.calls == [["/usr/sbin/lsof", "-nP", "-iTCP", "-sTCP:LISTEN"]])
    }
}
