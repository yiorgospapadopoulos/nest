"""Read and validate the token file, and find the repository that holds it."""

import tomllib
from pathlib import Path

from pydantic import ValidationError

from nestd.design.errors import DesignError
from nestd.design.models import Tokens

TOKENS_FILE = Path("design") / "tokens.toml"


def load_tokens(path: Path) -> Tokens:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        msg = f"{path}: not found"
        raise DesignError(msg) from error
    except tomllib.TOMLDecodeError as error:
        msg = f"{path}: invalid TOML: {error}"
        raise DesignError(msg) from error
    try:
        return Tokens.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
        msg = f"{path}: {problems}"
        raise DesignError(msg) from error


def find_root(start: Path) -> Path:
    for folder in (start, *start.parents):
        if (folder / TOKENS_FILE).is_file():
            return folder
    msg = f"could not find {TOKENS_FILE.as_posix()} in {start} or any parent folder"
    raise DesignError(msg)
