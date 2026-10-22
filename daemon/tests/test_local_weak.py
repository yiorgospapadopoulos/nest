import pytest

from nestd.local.weak import rate, size_in_name


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("qwen3-8b", 8.0),
        ("Llama-3.1-70B-Instruct", 70.0),
        ("qwen3-coder-30b-a3b", 30.0),
        ("gemma-3n-e4b", 4.0),
        ("phi-3.5b-mini", 3.5),
        ("gpt-oss:20b", 20.0),
        ("mistral-small", None),
        ("bigcode", None),
    ],
)
def test_the_size_is_read_from_the_name(name: str, size: float | None) -> None:
    assert size_in_name(name) == size


def test_a_model_without_tool_use_is_none() -> None:
    assert rate(name="qwen3-32b", params=None, context=65536, tools=False, app="Ollama") == (
        "none",
        "This model cannot call tools, which an agent needs.",
    )


def test_a_small_context_is_weak_and_says_how_to_fix_it() -> None:
    assert rate(name="qwen3-32b", params=None, context=4096, tools=True, app="Ollama") == (
        "weak",
        "Context of 4k is too small for an agent: set Ollama to 64k.",
    )


def test_a_small_context_without_an_app_names_the_server() -> None:
    assert rate(name="big", params=32.0, context=8192, tools=None, app=None) == (
        "weak",
        "Context of 8k is too small for an agent: set the server to 64k.",
    )


def test_under_64k_is_too_small_for_claude_code_which_compacts_every_step() -> None:
    # Live (qwen3-4b, 40k): Claude Code's 23k-token prompt left no room, so it compacted
    # the chat after almost every step.
    assert rate(name="big", params=32.0, context=40960, tools=True, app="LM Studio") == (
        "weak",
        "Context of 40k is too small for an agent: set LM Studio to 64k.",
    )
    assert rate(name="big", params=32.0, context=65536, tools=True, app="LM Studio") == (
        "good",
        None,
    )


def test_a_small_model_is_weak() -> None:
    assert rate(name="qwen3-8b", params=None, context=65536, tools=True, app="LM Studio") == (
        "weak",
        "An 8B model is small for an agent: it often calls tools wrongly.",
    )


def test_the_server_size_wins_over_the_name() -> None:
    assert rate(name="qwen3-8b", params=1.5, context=None, tools=None, app=None) == (
        "weak",
        "A 1.5B model is small for an agent: it often calls tools wrongly.",
    )


def test_a_big_model_with_room_is_good() -> None:
    assert rate(name="qwen3-coder-30b", params=None, context=131072, tools=True, app=None) == (
        "good",
        None,
    )


def test_nothing_known_is_unknown() -> None:
    assert rate(name="mystery", params=None, context=None, tools=None, app=None) == (
        "unknown",
        None,
    )


def test_tool_use_alone_is_good() -> None:
    assert rate(name="mystery", params=None, context=None, tools=True, app=None) == ("good", None)
