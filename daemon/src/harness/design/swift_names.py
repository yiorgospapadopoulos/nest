"""Map snake_case token names to Swift identifiers, escaping reserved words."""

_RESERVED = frozenset(
    (
        "associatedtype",
        "class",
        "deinit",
        "enum",
        "extension",
        "fileprivate",
        "func",
        "import",
        "init",
        "inout",
        "internal",
        "let",
        "open",
        "operator",
        "private",
        "precedencegroup",
        "protocol",
        "public",
        "rethrows",
        "static",
        "struct",
        "subscript",
        "typealias",
        "var",
        "break",
        "case",
        "catch",
        "continue",
        "default",
        "defer",
        "do",
        "else",
        "fallthrough",
        "for",
        "guard",
        "if",
        "in",
        "repeat",
        "return",
        "throw",
        "switch",
        "where",
        "while",
        "Any",
        "as",
        "await",
        "false",
        "is",
        "nil",
        "self",
        "Self",
        "super",
        "throws",
        "true",
        "try",
        "Protocol",
        "Type",
    )
)


def member_name(name: str) -> str:
    first, *rest = name.split("_")
    return _escape(first + "".join(part.capitalize() for part in rest))


def type_name(name: str) -> str:
    return _escape("".join(part.capitalize() for part in name.split("_")))


def _escape(identifier: str) -> str:
    return f"`{identifier}`" if identifier in _RESERVED else identifier
