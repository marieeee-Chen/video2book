"""Stable contracts; domain adapters own filenames, semantics and requirements."""
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceRange:
    source_id: str
    start: float
    end: float
    unit: str


@dataclass(frozen=True)
class Product:
    directory: str
    patterns: tuple[str, ...]
    required: bool = False
    min_bytes: int = 1
    preserve_existing: bool = False

    def files(self, workspace: Path) -> list[Path]:
        return sorted({p for pattern in self.patterns
                       for p in (workspace / self.directory).glob(pattern) if p.is_file()})


@dataclass(frozen=True)
class Profile:
    tool: str
    products: tuple[Product, ...]
    read_only_target: bool = False


@dataclass(frozen=True)
class Task:
    task_id: str
    output: str
    inputs: tuple[str, ...]
    metadata: Any = None
    required: bool = True


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    path: str = ""
    severity: str = "error"


@dataclass
class Report:
    tool: str
    issues: list[Issue] = field(default_factory=list)
    schema_version: int = 1

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def as_dict(self) -> dict:
        return {**asdict(self), "ok": self.ok}

    def require(self) -> None:
        if not self.ok:
            raise ValueError("; ".join(f"{i.code}: {i.path} {i.message}"
                                      for i in self.issues if i.severity == "error"))
