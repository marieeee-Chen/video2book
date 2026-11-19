"""Failure/retry and source-range regressions, including real FFmpeg bytes."""
import copy
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.audio_evidence import receipt_path, valid_cache
from src.core.audio_materializer import AudioMaterializationError, AudioMaterializer
from src.core.block_plan import BlockPlan
from src.core.source_coverage import plan_coverage
from src.core.taskbook import page_audio_entries


@pytest.fixture
def real_audio(tmp_path, has_ffmpeg):
    if not has_ffmpeg:
        pytest.skip('ffmpeg/ffprobe required for real audio regression')
    path = tmp_path / 'source.m4a'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=6',
                    '-c:a', 'aac', str(path)], check=True, timeout=30)
    return path


def test_failed_concat_never_becomes_cache_and_retry_decodes(tmp_path, real_audio, monkeypatch):
    from src.core import audio_materializer as module
    target = tmp_path / 'block.m4a'
    real_runner = module.run_quiet
    def fail(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b'partial ffmpeg output')
        return SimpleNamespace(returncode=1, stderr='injected disk failure')
    monkeypatch.setattr(module, 'run_quiet', fail)
    with pytest.raises(AudioMaterializationError):
        AudioMaterializer._concat(target, [real_audio, real_audio], duration=12)
    assert not target.exists() and not valid_cache(target)
    assert not list(tmp_path.glob('.block-*.m4a'))
    monkeypatch.setattr(module, 'run_quiet', real_runner)
    AudioMaterializer._concat(target, [real_audio, real_audio], duration=12)
    assert valid_cache(target)
    target.write_bytes(b'nonempty corruption')
    assert not valid_cache(target)


def test_slice_source_change_and_duration_mismatch(tmp_path, real_audio):
    target = tmp_path / 'slice.m4a'
    AudioMaterializer._slice_unit(real_audio, target, 3, 3)
    assert valid_cache(target)
    old = target.read_bytes()
    with pytest.raises(AudioMaterializationError):
        AudioMaterializer._slice_unit(real_audio, target, 5, 20)
    assert target.read_bytes() == old and valid_cache(target)
    real_audio.write_bytes(b'new source')
    assert not valid_cache(target)


def test_missing_mixed_leg_rebuilt_even_when_block_cache_exists(make_workspace, real_audio):
    ws = make_workspace('mixed_local')
    parts = [{'page': 1, 'title': 'long', 'duration': 6, 'cid': 1},
             {'page': 2, 'title': 'short', 'duration': 3, 'cid': 2}]
    plan = BlockPlan.plan_from_parts(parts)
    long = plan['blocks'][0]['units'][0]
    unit1 = {**long, 'split': True, 'label': 'P01下', 'source_offset_sec': 3., 'start_sec': 3., 'end_sec': 6., 'duration_sec': 3.}
    unit2 = {**plan['blocks'][0]['units'][1]}
    block = {**plan['blocks'][0], 'units': [unit1, unit2], 'episode_split': True, 'duration_sec': 6.}
    block['segments'] = [dict(page=u['page'], label=u['label'], duration_sec=3.) for u in block['units']]
    def fetch(part, target):
        if part['page'] == 1:
            shutil.copyfile(real_audio, target)
        else:
            AudioMaterializer._slice_unit(real_audio, target, 0, 3)
        return target
    kwargs = dict(ws=ws, info={'platform': 'local'}, blocks=[block], parts={p['page']: p for p in parts}, fetch_episode=fetch)
    result = AudioMaterializer.materialize(**kwargs)
    assert valid_cache(result[1])
    leg = AudioMaterializer.parts_dir(ws) / 'BLK01_P01下.m4a'
    leg.unlink(); receipt_path(leg).unlink()
    AudioMaterializer.materialize(**kwargs)
    assert valid_cache(leg)
    assert page_audio_entries(ws, block, [1])[0]['audio'] == str(leg.resolve())


def test_selected_complete_block_never_deletes_unfinished_consumer(make_workspace):
    ws = make_workspace('retain')
    plan = BlockPlan.ensure(ws, [{'page': 1, 'duration': 5400, 'title': 'long'}])
    assert len(plan['blocks']) == 2
    audio = ws.audio_dir / 'P01_long.m4a'; audio.write_bytes(b'keep input')
    result = AudioMaterializer.purge_audio(ws, plan['blocks'][:1])
    assert not result['purged'] and audio.read_bytes() == b'keep input'


def test_second_half_missing_is_seconds_gap_even_when_page_present():
    plan = BlockPlan.plan_from_parts([{'page': 1, 'cid': 123, 'duration': 5400}])
    assert plan_coverage(plan) == []
    plan['blocks'].pop()
    assert any('coverage_gap' in issue for issue in plan_coverage(plan))


@pytest.mark.parametrize('mutation', ['identity', 'offset', 'overlap', 'unknown_duration'])
def test_invalid_source_evidence_fails(mutation):
    plan = BlockPlan.plan_from_parts([{'page': 1, 'cid': 123, 'duration': 5400}])
    if mutation == 'identity': plan['blocks'][0]['units'][0]['source']['cid'] = 456
    if mutation == 'offset': plan['blocks'][1]['units'][0]['source_offset_sec'] = 0
    if mutation == 'overlap': plan['blocks'].append(copy.deepcopy(plan['blocks'][0]))
    if mutation == 'unknown_duration': plan['source']['parts'][0]['duration'] = 0
    assert plan_coverage(plan)


def test_short_page_identity_never_implies_complete_coverage():
    plan = BlockPlan.plan_from_parts([{'page': 1, 'cid': 123, 'duration': 180}])
    block = plan['blocks'][0]
    block['duration_sec'] = 50
    for unit in block['units'] + block['segments']:
        unit['duration_sec'] = unit['end_sec'] = 50
    assert any('coverage_gap' in issue for issue in plan_coverage(plan))
