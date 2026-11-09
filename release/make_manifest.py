"""Write latest.json for a release folder: the version, its notes and each file's sha256, and
latest.json.sig, its signature by the release key in the Keychain (`release_key.py`).

Every file sits on one line, because `install.sh` reads this with `sed` on machines that
have neither `jq` nor Python. Names are relative to the release address, which the script
and the daemon take from NEST_RELEASE_URL. `uv` comes from Astral, so it has a full address.

    make_manifest.py <release folder> <version> <notes file> <uv version>
"""

import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

from release_key import sign

from nestd.updates.signature import SIGNATURE_SUFFIX

UV_ADDRESS = "https://github.com/astral-sh/uv/releases/download"
UV_TARGETS = {
    "macos-arm64": "aarch64-apple-darwin",
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "linux-arm64": "aarch64-unknown-linux-gnu",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def kind_of(name: str) -> tuple[str, str] | None:
    """A release file's kind and the platform it is for; None for files not listed."""
    patterns = (
        (r"Nest-.+-macos-arm64\.zip", "app", "macos-arm64"),
        (r"Nest-.+-linux-(x86_64|arm64)\.AppImage", "app", None),
        (r"Nest-.+-linux-(x86_64|arm64)\.deb", "deb", None),
        (r"nestd-.+-py3-none-any\.whl", "wheel", "any"),
        (r"nestd-.+-requirements\.txt", "requirements", "any"),
        (r"install\.sh", "script", "any"),
    )
    for pattern, kind, platform in patterns:
        match = re.fullmatch(pattern, name)
        if match:
            return kind, platform or f"linux-{match[1]}"
    return None


def uv_entry(platform: str, target: str, version: str) -> dict[str, str]:
    name = f"uv-{target}.tar.gz"
    address = f"{UV_ADDRESS}/{version}/{name}"
    with urllib.request.urlopen(f"{address}.sha256", timeout=30) as response:  # noqa: S310
        digest = response.read().decode().split()[0]
    return {"platform": platform, "kind": "uv", "name": address, "sha256": digest}


def main() -> int:
    folder, version, notes, uv_version = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    entries = [
        {"platform": found[1], "kind": found[0], "name": path.name, "sha256": sha256(path)}
        for path in sorted(folder.iterdir())
        if (found := kind_of(path.name)) is not None
    ]
    entries += [uv_entry(p, t, uv_version) for p, t in UV_TARGETS.items()]
    head = {"version": version, "notes": Path(notes).read_text(encoding="utf-8").strip()}
    lines = ",\n".join("    " + json.dumps(entry) for entry in entries)
    body = json.dumps(head, indent=2)[:-2]
    manifest = f'{body},\n  "files": [\n{lines}\n  ]\n}}\n'.encode()
    json.loads(manifest)
    # The exact bytes the clients read are signed, so nothing may rewrite the file after this.
    (folder / "latest.json").write_bytes(manifest)
    (folder / f"latest.json{SIGNATURE_SUFFIX}").write_bytes(sign(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
