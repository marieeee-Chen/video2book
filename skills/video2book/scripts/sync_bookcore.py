#!/usr/bin/env python3
"""Distribute the canonical core; default is a read-only drift check."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from src.core.console import enable_utf8_console  # noqa: E402

SOURCE = SKILL / "src" / "bookcore"


def sync(workspace: Path, write=False):
    payloads = {p.name: p.read_bytes() for p in SOURCE.iterdir()
                if p.is_file() and p.name != "RELEASE.json"}
    release = {
        "version": "0.1.0",
        "origin": "video2book/skills/video2book/src/bookcore",
        "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payloads.items())},
    }
    payloads["RELEASE.json"] = (json.dumps(release, indent=2) + "\n").encode()
    targets = [SOURCE] + [workspace / tool / "src" / tool / "_bookcore"
                          for tool in ("wechat2book", "book2book", "chat2book")]
    drift = []
    for target in targets:
        if write:
            target.mkdir(parents=True, exist_ok=True)
        for name, data in payloads.items():
            path = target / name
            if not path.is_file() or path.read_bytes() != data:
                if write:
                    path.write_bytes(data)
                else:
                    drift.append(str(path))
        if target.exists():
            for path in target.iterdir():
                if path.is_file() and path.name not in payloads:
                    if write:
                        path.unlink()
                    else:
                        drift.append(str(path))
    return drift


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--write", action="store_true", help="Replace bundled copies from canonical source")
    args = parser.parse_args()
    drift = sync(args.workspace.resolve(), args.write)
    print("\n".join(drift) if drift else "bookcore bundles match release 0.1.0")
    return int(bool(drift))


if __name__ == "__main__":
    enable_utf8_console()
    raise SystemExit(main())
