"""Split audio taskbooks must never repeat a full-page untimed transcript."""
from pathlib import Path
import pytest
from src.core.block_plan import BlockPlan
from src.core.taskbook import TRANSCRIBE_INSTRUCTION, export_page_transcribe_task, page_audio_entries


def split_block(label='P20中1', number=34):
    unit = {'page': 20, 'label': label, 'split': True,
            'source_offset_sec': 2804.33, 'start_sec': 2804.33,
            'end_sec': 5608.67, 'duration_sec': 2804.34,
            'source': {'page': 20, 'cid': 1576241899, 'title': '哈贝马斯', 'duration': 8413}}
    return {'block_id': number, 'title': '哈贝马斯', 'span': label,
            'episodes': [20], 'units': [unit], 'episode_split': True,
            'segments': [{'page': 20, 'label': label, 'start_sec': 2804.33,
                          'end_sec': 5608.67, 'duration_sec': 2804.34}]}


@pytest.mark.parametrize('label', ['P20上', 'P20中1', 'P20下'])
def test_all_split_labels_use_exact_unit_audio(make_workspace, label):
    ws = make_workspace('split-task')
    block = split_block(label)
    exact = BlockPlan.blocks_dir(ws) / '_parts' / f'BLK34_{label}.m4a'
    exact.parent.mkdir(parents=True, exist_ok=True)
    exact.write_bytes(b'exact physical clip')
    full = BlockPlan.source_audio_path(ws, block['units'][0]['source'])
    full.write_bytes(b'full page must not be selected')
    entry = page_audio_entries(ws, block, [20])[0]
    assert Path(entry['audio']) == exact.resolve()
    assert entry['split'] is True
    assert entry['start_offset_sec'] == 2804.33
    text = export_page_transcribe_task(ws, block, [20]).read_text()
    assert str(exact.resolve()) in text and str(full.resolve()) not in text
    assert '2804.33–5608.67s' in text
    assert '不再次施加原片偏移' in text
    assert 'is_finished=true' in text
    assert TRANSCRIBE_INSTRUCTION in text


def test_single_unit_cached_block_is_exact_fallback(make_workspace):
    ws = make_workspace('cached-clip')
    block = split_block()
    target = BlockPlan.audio_path(ws, block)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'exact one-unit block')
    assert Path(page_audio_entries(ws, block, [20])[0]['audio']) == target.resolve()


def test_missing_split_clip_does_not_fall_back_to_full_page(make_workspace):
    ws = make_workspace('no-exact-clip')
    block = split_block()
    BlockPlan.source_audio_path(ws, block['units'][0]['source']).write_bytes(b'full page')
    with pytest.raises(ValueError, match='禁止整集补录'):
        export_page_transcribe_task(ws, block, [20])


def test_whole_episode_keeps_original_audio_path(make_workspace):
    ws = make_workspace('whole-episode')
    block = split_block('P20')
    block['units'][0]['split'] = False
    entry = page_audio_entries(ws, block, [20])[0]
    assert Path(entry['audio']) == BlockPlan.source_audio_path(ws, block['units'][0]['source']).resolve()
    assert entry['split'] is False
