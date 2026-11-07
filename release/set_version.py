"""Write the root VERSION file to every place that holds a version, or check them.

    set_version.py            write VERSION everywhere
    set_version.py --check    list what differs and exit 1 if anything does

The Mac app's build number goes up by one whenever its version changes.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Place:
    file: str
    # One group, the version. Only the first match counts, except where `count` says more.
    pattern: str
    count: int = 1


PLACES = (
    Place("daemon/pyproject.toml", r'^version = "([^"]+)"$'),
    Place("daemon/uv.lock", r'^name = "nestd"\nversion = "([^"]+)"$'),
    Place("desktop/src-tauri/tauri.conf.json", r'^  "version": "([^"]+)"'),
    Place("desktop/src-tauri/Cargo.toml", r'^version = "([^"]+)"$'),
    Place("desktop/src-tauri/Cargo.lock", r'^name = "nest-desktop"\nversion = "([^"]+)"$'),
    Place(
        "apple/support/Info.plist",
        r"<key>CFBundleShortVersionString</key>\s*<string>([^<]+)</string>",
    ),
    Place("web/package.json", r'^  "version": "([^"]+)"'),
    Place("web/package-lock.json", r'^ +"version": "([^"]+)"', count=2),
)
_BUILD_NUMBER = re.compile(r"(<key>CFBundleVersion</key>\s*<string>)(\d+)(</string>)")


def found(place: Place, text: str) -> list[re.Match[str]]:
    return list(re.finditer(place.pattern, text, re.MULTILINE))[: place.count]


def differences(version: str) -> list[str]:
    problems: list[str] = []
    for place in PLACES:
        matches = found(place, (ROOT / place.file).read_text(encoding="utf-8"))
        if len(matches) != place.count:
            problems.append(f"{place.file}: no version found")
        problems += [
            f"{place.file}: {match[1]}, not {version}" for match in matches if match[1] != version
        ]
    return problems


def write(version: str) -> None:
    for place in PLACES:
        path = ROOT / place.file
        text = path.read_text(encoding="utf-8")
        matches = found(place, text)
        if not matches or all(match[1] == version for match in matches):
            continue
        for match in reversed(matches):
            text = text[: match.start(1)] + version + text[match.end(1) :]
        if place.file.endswith("Info.plist"):
            text = _BUILD_NUMBER.sub(
                lambda m: f"{m[1]}{int(m[2]) + 1}{m[3]}",
                text,
                count=1,
            )
        path.write_text(text, encoding="utf-8")


def main() -> int:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if "--check" not in sys.argv:
        write(version)
    problems = differences(version)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
