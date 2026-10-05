"""Shared file and Markdown checks; no claims of semantic fidelity."""
from pathlib import Path
import math

from .contracts import Issue, Report
from .deliverable_lint import (
    fatal_note_total, fatal_render_total, lint_note, lint_note_filename,
    lint_render, summarize_note, summarize_render,
)
from .io import relative_path


def check_products(workspace: Path, profile) -> Report:
    report = Report(profile.tool)
    for product in profile.products:
        paths = product.files(workspace)
        if product.required and not paths:
            report.issues.append(Issue("missing_product", "Required product is absent", product.directory))
        for path in paths:
            name = path.relative_to(workspace).as_posix()
            try:
                relative_path(workspace, name)
                if path.stat().st_size < product.min_bytes:
                    report.issues.append(Issue("short_product", "Product is empty or too short", name))
            except (OSError, ValueError) as exc:
                report.issues.append(Issue("unsafe_product", str(exc), name))
    return report


def check_markdown(paths, *, tool, notes=(), max_truncated=4) -> Report:
    report = Report(tool)
    note_set = set(notes)
    for path in sorted(set(paths)):
        text = path.read_text(encoding="utf-8")
        if fatal_render_total(summarize_render(lint_render(text))):
            report.issues.append(Issue("render", "Fatal Markdown rendering issue", str(path)))
        if path in note_set:
            counts = summarize_note(lint_note(text))
            # Truncated bullet lines have a configurable historical tolerance.
            counts["truncated"] = max(0, counts.get("truncated", 0) - max_truncated)
            if fatal_note_total(counts) or counts["truncated"] or lint_note_filename(path.name):
                report.issues.append(Issue("note_lint", "Fatal note quality issue", str(path)))
    return report


def check_coverage(sources, spans, *, tool, allow_overlap=False) -> Report:
    """Validate ranges in declared units; omission handling belongs to the adapter."""
    result = Report(tool)
    expected = {}
    for source in sources:
        if source.source_id in expected or not source.start < source.end:
            result.issues.append(Issue("invalid_source", "Duplicate or empty source range", source.source_id))
        expected[source.source_id] = source
    covered = {sid: [] for sid in expected}
    for span in spans:
        source = expected.get(span.source_id)
        if (source is None or span.unit != source.unit or
                not all(math.isfinite(v) for v in (span.start, span.end)) or
                not source.start <= span.start < span.end <= source.end):
            result.issues.append(Issue("invalid_span", "Unknown source, incompatible unit or out-of-bounds range", span.source_id))
            continue
        covered[span.source_id].append((span.start, span.end))
    for sid, source in expected.items():
        cursor = source.start
        for start, end in sorted(covered[sid]):
            if start > cursor:
                result.issues.append(Issue("coverage_gap", f"Uncovered range [{cursor}, {start})", sid))
            if start < cursor and not allow_overlap:
                result.issues.append(Issue("coverage_overlap", "Source range is claimed more than once", sid))
            cursor = max(cursor, end)
        if cursor < source.end:
            result.issues.append(Issue("coverage_gap", f"Uncovered tail [{cursor}, {source.end})", sid))
    return result
