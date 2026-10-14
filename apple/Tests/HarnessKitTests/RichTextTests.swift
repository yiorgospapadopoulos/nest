import Foundation
import Testing

@testable import HarnessKit

@Suite struct RichTextTests {
    @Test func inlineMarkdownBecomesStyledRuns() {
        let runs = RichText.runs("Use **zod** and *then* `npm test` ~~now~~ ***both***")
        #expect(
            runs == [
                TextRun("Use "), TextRun("zod", style: .bold), TextRun(" and "),
                TextRun("then", style: .italic), TextRun(" "), TextRun("npm test", style: .code),
                TextRun(" "), TextRun("now", style: .strikethrough), TextRun(" "),
                TextRun("both", style: [.bold, .italic]),
            ])
    }

    @Test func linksKeepTheirTarget() {
        let runs = RichText.runs("See [the docs](https://zod.dev/api) here")
        #expect(
            runs == [
                TextRun("See "), TextRun("the docs", link: URL(string: "https://zod.dev/api")),
                TextRun(" here"),
            ])
    }

    /// Only web and mail links open; a `file:` link to a `.command` file would run it, and
    /// app schemes launch other apps, so they show as plain text (audit SEC-03).
    @Test func onlyWebAndMailLinksStayLinks() {
        let runs = RichText.runs(
            "[report](file:///tmp/x.command) [prefs](x-apple.systempreferences:com.apple) [code](vscode://file/a) [mail](mailto:me@example.com) [site](HTTP://example.com)"
        )
        #expect(runs.filter { $0.link != nil }.map(\.text) == ["mail", "site"])
        #expect(runs.map(\.text).joined() == "report prefs code mail site")
    }

    @Test func safeLinksAllowWebAndMailOnly() {
        #expect(SafeLink.url("https://github.com/o/r/pull/1")?.host == "github.com")
        #expect(SafeLink.url("http://example.com") != nil)
        #expect(SafeLink.url("mailto:me@example.com") != nil)
        #expect(SafeLink.url("file:///tmp/x.command") == nil)
        #expect(SafeLink.url("ssh://host") == nil)
        // Schemes that run script or open apps stay text, whatever their case (audit M-8).
        for link in [
            "javascript:alert(1)", "JavaScript:alert(1)", "vbscript:msgbox(1)",
            "data:text/html,<script>alert(1)</script>", "x-apple.systempreferences:", "tel:123",
        ] {
            #expect(SafeLink.url(link) == nil, "\(link)")
        }
        #expect(SafeLink.url("no scheme") == nil)
        #expect(SafeLink.url("") == nil)
    }

    @Test func bareURLsBecomeLinksOutsideCode() {
        let runs = RichText.runs("Open https://example.com/a?b=1 or `https://not.linked`")
        #expect(
            runs == [
                TextRun("Open "),
                TextRun(
                    "https://example.com/a?b=1", link: URL(string: "https://example.com/a?b=1")),
                TextRun(" or "), TextRun("https://not.linked", style: .code),
            ])
    }

    @Test func unreadableMarkdownIsShownAsWritten() {
        struct Unreadable: Error {}
        let runs = RichText.runs("**half") { _ in throw Unreadable() }
        #expect(runs == [TextRun("**half")])
    }

    @Test func softLineBreaksArePreserved() {
        #expect(RichText.runs("one\ntwo") == [TextRun("one\ntwo")])
        #expect(RichText.runs("") == [])
    }

    @Test func blocksBecomeParagraphsWithRolesAndSpacing() {
        let text =
            "# Title\nIntro with `code`\n\n- one\n- two\n  - deep\n\n```swift\nlet a = 1\n```\nEnd"
        #expect(
            RichText.paragraphs(text) == [
                RichParagraph(role: .heading(level: 1), runs: [TextRun("Title")], spacing: .none),
                RichParagraph(
                    role: .body, runs: [TextRun("Intro with "), TextRun("code", style: .code)],
                    spacing: .block),
                RichParagraph(
                    role: .listItem(marker: "•", level: 0), runs: [TextRun("one")],
                    spacing: .block),
                RichParagraph(
                    role: .listItem(marker: "•", level: 0), runs: [TextRun("two")],
                    spacing: .tight),
                RichParagraph(
                    role: .listItem(marker: "•", level: 1), runs: [TextRun("deep")],
                    spacing: .tight),
                RichParagraph(
                    role: .code(language: "swift"), runs: [TextRun("let a = 1", style: .code)],
                    spacing: .block),
                RichParagraph(role: .body, runs: [TextRun("End")], spacing: .block),
            ])
    }

    @Test func listItemsShowTheirMarkerBeforeTheText() {
        let paragraphs = RichText.paragraphs("## Plan\n- **one**\n1. two\n\n```\na\nb\n```")
        #expect(paragraphs.map(\.prefix) == ["", "•\t", "1.\t", ""])
        #expect(paragraphs.map { $0.runs.map(\.text).joined() } == ["Plan", "one", "two", "a\nb"])
    }
}
