"""Content-stable assembly writes; ordering and prose remain domain-owned."""
from pathlib import Path

from .io import relative_path, write_text


def write_books(directory: Path, rendered: dict[str, str], pattern: str) -> list[Path]:
    if not rendered:
        raise ValueError("Refusing to replace books with an empty assembly")
    expected = {name: relative_path(directory, name) for name in rendered}
    if any(path.parent != directory.resolve() for path in expected.values()):
        raise ValueError("Book outputs must be direct children")
    for name, text in rendered.items():
        if not text.strip():
            raise ValueError(f"Empty book: {name}")
    for name, path in expected.items():
        write_text(path, rendered[name])
    for old in directory.glob(pattern):
        if old.name not in expected:
            old.unlink()
    return list(expected.values())
