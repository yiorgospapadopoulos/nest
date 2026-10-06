import dataclasses
import io
from pathlib import Path

import pytest

from harness.cli import main
from harness.design.outputs import CSS_OUTPUT, SWIFT_OUTPUT, stale_outputs
from harness.runtime import Runtime, default_runtime
from tests.design_support import REPO_ROOT, minimal_tokens, write_tokens


@dataclasses.dataclass
class Console:
    runtime: Runtime
    out: io.StringIO
    err: io.StringIO

    def run(self, *argv: str) -> int:
        return main(list(argv), self.runtime)


@pytest.fixture
def console() -> Console:
    out, err = io.StringIO(), io.StringIO()
    return Console(dataclasses.replace(default_runtime(), out=out, err=err), out, err)


def test_generate_writes_both_outputs(console: Console, tmp_path: Path) -> None:
    write_tokens(tmp_path, minimal_tokens())
    assert console.run("design", "generate", "--root", str(tmp_path)) == 0
    css = (tmp_path / CSS_OUTPUT).read_text(encoding="utf-8")
    swift = (tmp_path / SWIFT_OUTPUT).read_text(encoding="utf-8")
    assert "--text-primary: #1a1b20;" in css
    assert "public enum DesignTokens {" in swift
    assert console.out.getvalue() == f"Wrote {CSS_OUTPUT}\nWrote {SWIFT_OUTPUT}\n"


def test_the_root_defaults_to_the_nearest_folder_with_tokens(
    console: Console, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_tokens(tmp_path, minimal_tokens())
    nested = tmp_path / "daemon"
    nested.mkdir()
    monkeypatch.chdir(nested)
    assert console.run("design", "generate") == 0
    assert (tmp_path / CSS_OUTPUT).is_file()


def test_check_reports_missing_and_stale_outputs(console: Console, tmp_path: Path) -> None:
    write_tokens(tmp_path, minimal_tokens())
    root = str(tmp_path)
    assert console.run("design", "check", "--root", root) == 1
    err = console.err.getvalue()
    assert f"harness: {CSS_OUTPUT} is missing\n" in err
    assert f"harness: {SWIFT_OUTPUT} is missing\n" in err
    assert err.endswith("harness: run `harness design generate` to update them\n")

    console.run("design", "generate", "--root", root)
    assert console.run("design", "check", "--root", root) == 0
    assert console.out.getvalue().endswith("Design tokens are up to date\n")

    data = minimal_tokens()
    data["radius"]["window"] = 26
    write_tokens(tmp_path, data)
    console.err.truncate(0)
    console.err.seek(0)
    assert console.run("design", "check", "--root", root) == 1
    assert f"harness: {CSS_OUTPUT} is out of date\n" in console.err.getvalue()


def test_design_errors_exit_with_a_message(
    console: Console, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert console.run("design", "check") == 1
    assert "harness: could not find design/tokens.toml" in console.err.getvalue()
    data = minimal_tokens()
    del data["radius"]
    write_tokens(tmp_path, data)
    assert console.run("design", "generate", "--root", str(tmp_path)) == 1
    assert "radius: Field required" in console.err.getvalue()


def test_repository_outputs_are_up_to_date() -> None:
    assert stale_outputs(REPO_ROOT) == []
