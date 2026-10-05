"""Workspace-contained paths and atomic, content-stable writes."""
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath


def relative_path(root: Path, name: str) -> Path:
    raw = PurePosixPath(name)
    if not name or "\\" in name or raw.is_absolute() or ".." in raw.parts or not raw.parts:
        raise ValueError(f"Unsafe relative path: {name}")
    root = Path(root).resolve()
    target = root.joinpath(*raw.parts)
    if not target.resolve().is_relative_to(root):
        raise ValueError(f"Path escapes workspace: {name}")
    for part in (target, *target.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError(f"Symlink is not a production input: {name}")
    return target


def file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str, *, force=False) -> bool:
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"Refusing to replace symlink: {path}")
    if not force and path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return True


def write_json(path: Path, value) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def exclusive_lock(path: Path):
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"State is busy or lock requires review: {path}") from exc
    os.close(fd)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
