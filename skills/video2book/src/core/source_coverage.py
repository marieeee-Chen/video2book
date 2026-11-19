"""Validate original-source seconds, never concatenated-block coordinates."""
import math

from src.bookcore.checks import check_coverage
from src.bookcore.contracts import SourceRange
from .block_plan import BlockPlan


def plan_coverage(plan):
    sources, spans, issues = [], [], []
    parts = {}
    excluded = plan.get('excluded_pages', {})
    if not isinstance(excluded, dict) or any(not isinstance(v, str) or not v.strip() for v in excluded.values()):
        return ['invalid_exclusion: excluded_pages requires an explicit reason']
    for part in plan.get('source', {}).get('parts', []):
        page = str(part['page'])
        duration = BlockPlan._record_duration(part)
        if page in parts or duration <= 0:
            issues.append(f'invalid_source: P{page} requires unique identity and known positive duration')
            continue
        parts[page] = part
        sources.append(SourceRange(page, 0, duration, 'seconds'))
        if page in excluded:
            spans.append(SourceRange(page, 0, duration, 'seconds'))
    if not sources:
        issues.append('invalid_source: no measured source durations')
    if set(excluded) - set(parts):
        issues.append('invalid_exclusion: unknown source pages')
    for block in plan.get('blocks', []):
        units, segments = block.get('units', []), block.get('segments', [])
        if not units or len(units) != len(segments):
            issues.append(f'invalid_span: BLK{block.get("block_id")} requires matching units/segments')
            continue
        cursor = 0.0
        for unit, segment in zip(units, segments):
            page = str(unit['page'])
            start = float(unit['source_offset_sec'])
            end = float(unit['end_sec'])
            spans.append(SourceRange(page, start, round(end, 2), 'seconds'))
            numbers = [start, end, float(unit['start_sec']), float(unit['end_sec']),
                       float(segment['start_sec']), float(segment['end_sec']), float(segment['duration_sec']),
                       float(unit['duration_sec']), float(segment.get('source', {}).get('offset_sec', -1))]
            if (not all(math.isfinite(n) for n in numbers) or str(segment['page']) != page
                    or abs(start - numbers[2]) > .02 or abs((end-start) - float(unit['duration_sec'])) > .02
                    or abs(numbers[4] - cursor) > .02 or abs(numbers[5] - numbers[4] - (end-start)) > .02
                    or abs(numbers[6] - (end-start)) > .02
                    or abs(float(segment.get('source', {}).get('offset_sec', -1)) - start) > .02):
                issues.append(f'invalid_span: BLK{block.get("block_id")} P{page} inconsistent coordinates')
            cursor = numbers[5]
            for key in ('cid', 'video_id', 'filepath'):
                expected = parts.get(page, {}).get(key)
                if expected is not None and (unit.get('source', {}).get(key) != expected
                        or segment.get('source', {}).get('metadata', {}).get(key) != expected):
                    issues.append(f'source_identity: P{page} {key} mismatch')
        if not math.isfinite(float(block['duration_sec'])) or abs(cursor - float(block['duration_sec'])) > .02:
            issues.append(f'invalid_span: BLK{block.get("block_id")} total duration mismatch')
    report = check_coverage(sources, spans, tool='video2book', allow_overlap=False)
    issues.extend(f'{i.code}: {i.path} {i.message}' for i in report.issues)
    return issues
