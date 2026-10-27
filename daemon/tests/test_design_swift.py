from nestd.design.loader import load_tokens
from nestd.design.swift import render_swift
from tests.design_support import REPO_ROOT


def test_repository_swift_is_deterministic_and_balanced() -> None:
    tokens = load_tokens(REPO_ROOT / "design" / "tokens.toml")
    swift = render_swift(tokens)
    assert swift == render_swift(tokens)
    assert swift.count("{") == swift.count("}")
    assert swift.count("(") == swift.count(")")
    assert "public static let headline: Double = 17" in swift
    assert (
        "public static let all: [AccentColor] = [graphite, ocean, teal, moss, clay, rose]" in swift
    )
    assert "public static let all: [GlassStyle] = [clear, frosted, smoke, bluegrey, deep]" in swift
    assert 'name: "bluegrey", displayName: "Blue Grey",' in swift
