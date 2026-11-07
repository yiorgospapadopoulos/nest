import Foundation
import NestKit
import Testing

@Suite struct SafeLinkTests {
    @Test func onlyWebPagesOpenAndTheReportOnlyOnGitHub() {
        #expect(SafeLink.web("https://tailscale.com/download") != nil)
        #expect(SafeLink.web("file:///etc/passwd") == nil)
        #expect(SafeLink.web("x-apple.systempreferences:com.apple.Lock") == nil)
        #expect(SafeLink.web("http://example.com") == nil)
        #expect(SafeLink.githubIssue("https://github.com/o/r/issues/new?title=a") != nil)
        #expect(SafeLink.githubIssue("https://evil.example/issues/new") == nil)
    }
}
