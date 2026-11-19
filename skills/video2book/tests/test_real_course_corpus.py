"""Fixed observed source bytes; technical findings never grant content approval."""
import hashlib
import json
import math
from pathlib import Path

from src.core.deliverable_lint import lint_render
from src.core.source_coverage import plan_coverage

ROOT = Path(__file__).parent / 'fixtures/evidence'


def test_recorded_source_bytes_and_fatal_rules():
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    for case in manifest['cases']:
        if 'fixture' in case:
            assert hashlib.sha256((ROOT / case['fixture']).read_bytes()).hexdigest() == case['sha256']
    assert lint_render((ROOT / 'formula-broken.md').read_text())['formula_breaks']
    assert lint_render((ROOT / 'self-talk.md').read_text())['cot_leaks']


def test_real_long_page_loses_second_range():
    plan = json.loads((ROOT / 'long-page-plan.json').read_text())
    assert len(plan['blocks']) > 1
    assert plan_coverage(plan) == []
    plan['blocks'].pop()
    assert any('coverage_gap' in item for item in plan_coverage(plan))


def test_known_numeric_error_and_rebuilt_example():
    # Independent arithmetic, not string matching against generated prose.
    correct = math.degrees(math.acos(-math.sqrt(6) / 6))
    assert abs(correct - 114.0948425521107) < 1e-10
    assert abs(correct - 155.3) > 40
    z = 14 / 9
    assert abs(17 + (z-7)**2 - (34 + (z+2)**2)) < 1e-10
    assert math.isclose(sum(v*v for v in (3,3*math.sqrt(2),3)), 36)
