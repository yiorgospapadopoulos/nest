import Foundation
import Testing

@testable import NestKit

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

    /// Foundation's parser does link bare addresses; what follows is what agents write.
    @Test func aBareAddressLeavesThePunctuationAfterIt() {
        let text =
            "See https://a.dev/x. Or (https://b.dev/y), https://c.dev/p_(q) and https://d.dev?"
        let runs = RichText.runs(text)
        #expect(
            runs.compactMap { $0.link?.absoluteString } == [
                "https://a.dev/x", "https://b.dev/y", "https://c.dev/p_(q)", "https://d.dev",
            ])
        #expect(runs.map(\.text).joined() == text)
    }

    @Test func anAddressInAngleBracketsShowsNoBrackets() {
        let runs = RichText.runs("Open <https://a.dev/x> now")
        #expect(runs.compactMap { $0.link?.absoluteString } == ["https://a.dev/x"])
        #expect(runs.map(\.text).joined() == "Open https://a.dev/x now")
    }

    @Test func onlyWebAddressesLinkAndALinkHoldsNoOther() {
        let runs = RichText.runs("<javascript:alert(1)> ftp://a.dev [https://a.dev](https://b.dev)")
        #expect(runs.compactMap { $0.link?.absoluteString } == ["https://b.dev"])
    }

    @Test func escapedMarksShowTheirCharacterButNotInCode() {
        let runs = RichText.runs(##"\*not em\* \[a\](b) \# \| \` and `\*code\*`"##)
        #expect(runs.map(\.text).joined() == #"*not em* [a](b) # | ` and \*code\*"#)
        #expect(runs.filter { $0.style.contains(.italic) }.isEmpty)
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

    @Test func aTableBecomesOneParagraphWithInlineMarksInItsCells() {
        let paragraphs = RichText.paragraphs("| a | b |\n|--|-:|\n| **x** | 1 |")
        #expect(
            paragraphs == [
                RichParagraph(
                    role: .table(
                        RichTable(
                            aligns: [.leading, .trailing],
                            header: [[TextRun("a")], [TextRun("b")]],
                            rows: [[[TextRun("x", style: .bold)], [TextRun("1")]]])),
                    runs: [], spacing: .none)
            ])
    }

    @Test func aQuoteMarksItsParagraphs() {
        let paragraphs = RichText.paragraphs("> one\n>\n> two\n\nAfter")
        #expect(paragraphs.map(\.quoted) == [true, true, false])
    }

    @Test func blocksUnderAnItemKeepItsLevelAndItsSublistsGoDeeper() {
        let paragraphs = RichText.paragraphs("1. one\n\n   more\n\n   - sub\n\n     deep\n2. two")
        #expect(
            paragraphs.map(\.role) == [
                .listItem(marker: "1.", level: 0), .body, .listItem(marker: "•", level: 1), .body,
                .listItem(marker: "2.", level: 0),
            ])
        #expect(
            paragraphs.map(\.under) == [
                nil, RichParagraph.Under(level: 0, marker: "1."), nil,
                RichParagraph.Under(level: 1, marker: "•"), nil,
            ])
    }

    @Test func aRuleIsAParagraphThatCopiesAsItsMark() {
        #expect(
            RichText.paragraphs("---") == [
                RichParagraph(role: .rule, runs: [TextRun("---")], spacing: .none)
            ])
    }

    @Test func listItemsShowTheirMarkerBeforeTheText() {
        let paragraphs = RichText.paragraphs("## Plan\n- **one**\n1. two\n\n```\na\nb\n```")
        #expect(paragraphs.map(\.prefix) == ["", "•\t", "1.\t", ""])
        #expect(paragraphs.map { $0.runs.map(\.text).joined() } == ["Plan", "one", "two", "a\nb"])
    }
}

@Suite struct MessageCopyTests {
    private func table() -> NSMutableAttributedString {
        let text = NSMutableAttributedString(string: "Before\na\nb\n1\n2\nAfter")
        for (location, mark) in [(8, "\t"), (10, "\n"), (12, "\t"), (14, "\n")] {
            text.addAttribute(
                .copiedAs, value: mark, range: NSRange(location: location, length: 1))
        }
        return text
    }

    @Test func aRowCopiesOnOneLineAndRowsOnTheirOwn() {
        let text = table()
        #expect(MessageCopy.applies(to: text))
        #expect(
            MessageCopy.text(of: text, in: [NSRange(location: 0, length: text.length)])
                == "Before\na\tb\n1\t2\nAfter")
    }

    @Test func partOfARowCopiesOnlyWhatIsSelected() {
        let text = table()
        #expect(MessageCopy.text(of: text, in: [NSRange(location: 9, length: 3)]) == "b\n1")
    }

    @Test func textMarkedNotCopiedIsLeftOut() {
        let text = NSMutableAttributedString(string: "12 line")
        text.addAttribute(.notCopied, value: true, range: NSRange(location: 0, length: 3))
        #expect(MessageCopy.applies(to: text))
        #expect(MessageCopy.text(of: text, in: [NSRange(location: 0, length: 7)]) == "line")
    }

    @Test func plainTextCopiesTheUsualWay() {
        #expect(!MessageCopy.applies(to: NSAttributedString(string: "plain")))
    }
}

@Suite struct TableColumnsTests {
    private func sum(_ widths: [Double]) -> Double {
        widths.reduce(0, +)
    }

    @Test func columnsThatFitFillTheTableInProportion() {
        #expect(
            TableColumns.widths(longest: [100, 300], longestWord: [50, 50], room: 800) == [200, 600])
    }

    /// In a narrow pane too the short columns keep their numbers on one line; the long one
    /// wraps. A regression: fixed shares broke "200,000" in two.
    @Test(arguments: [640.0, 420.0, 300.0])
    func aLongColumnWrapsBeforeShortOnesBreak(room: Double) {
        let widths = TableColumns.widths(
            longest: [80, 900, 70], longestWord: [80, 90, 70], room: room)
        #expect(widths[0] >= 80)
        #expect(widths[1] >= 90)
        #expect(widths[2] >= 70)
        #expect(abs(sum(widths) - room) < 0.001)
    }

    @Test func tooManyColumnsShareByTheirLongestWord() {
        #expect(
            TableColumns.widths(longest: [500, 500], longestWord: [300, 900], room: 600) == [150, 450]
        )
    }

    @Test func anEmptyTableStillFillsItsRoom() {
        #expect(TableColumns.widths(longest: [0, 0], longestWord: [0, 0], room: 640) == [320, 320])
    }
}
