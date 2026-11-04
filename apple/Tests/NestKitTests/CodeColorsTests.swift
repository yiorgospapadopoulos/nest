import Foundation
import Testing

@testable import NestKit

@Suite("Code colours")
struct CodeColorsTests {
    private struct Sample: Decodable {
        let language: String
        let code: String
        let tokens: [[Value]]

        enum Value: Decodable, Equatable {
            case kind(String)
            case offset(Int)

            init(from decoder: Decoder) throws {
                let container = try decoder.singleValueContainer()
                if let offset = try? container.decode(Int.self) {
                    self = .offset(offset)
                } else {
                    self = .kind(try container.decode(String.self))
                }
            }
        }
    }

    private func shown(_ language: String, _ code: String) -> [String] {
        let units = Array(code.utf16)
        return CodeColors.tokens(language: language, code: code).map { token in
            let text = String(decoding: units[token.start..<token.end], as: UTF16.self)
            return "\(token.kind.rawValue): \(text)"
        }
    }

    @Test("a comment marker inside a string stays a string")
    func commentMarkerInString() {
        #expect(
            shown("ts", #"const url = "https://a.b/c"; // real"#) == [
                "keyword: const", #"string: "https://a.b/c""#, "comment: // real",
            ])
    }

    @Test("a half-written string ends with its line, a half-written block with the code")
    func unterminated() {
        #expect(
            shown("js", "let a = \"open\nlet b") == [
                "keyword: let", "string: \"open", "keyword: let",
            ]
        )
        #expect(shown("swift", "/* open") == ["comment: /* open"])
        #expect(shown("js", "\"\\") == ["string: \"\\"])
    }

    @Test("a keyword inside an identifier stays plain")
    func keywordInIdentifier() {
        #expect(shown("go", "format := forEach(iffy, a.for, for_x)") == [])
    }

    @Test("nothing is coloured without a known language or past the size cap")
    func plain() {
        #expect(CodeColors.tokens(language: nil, code: "const a = 1") == [])
        #expect(CodeColors.tokens(language: "cobol", code: "const a = 1") == [])
        let huge = String(repeating: "const a = 1\n", count: CodeColors.maxLength / 12 + 1)
        #expect(CodeColors.tokens(language: "ts", code: huge) == [])
    }

    @Test("agrees with the shared sample the web tokenizer is held to")
    func sharedSample() throws {
        let file = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appending(path: "design/code-colors-sample.json")
        let samples = try JSONDecoder().decode([Sample].self, from: Data(contentsOf: file))
        #expect(samples.count > 30)
        for sample in samples {
            let found = CodeColors.tokens(language: sample.language, code: sample.code)
                .map { [Sample.Value.kind($0.kind.rawValue), .offset($0.start), .offset($0.end)] }
            #expect(found == sample.tokens, "\(sample.language): \(sample.code)")
        }
    }
}
