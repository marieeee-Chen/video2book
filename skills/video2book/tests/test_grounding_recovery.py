"""Grounding regressions: translated prose, code, and false source ranges."""
import hashlib
import json
from pathlib import Path

import pytest

from conftest import write_blocks
from src.core.quality_gate import (
    DEFAULT_MIN_COVERAGE, check_grounding_block, check_grounding_workspace,
    check_production_workspace, check_transcript_ranges_workspace,
    extract_entities, run_stage1, strip_transcript_header,
)
from src.core.workspace import TaskWorkspace, module_article_path


def test_english_function_words_do_not_demand_literal_chinese_copy():
    prose = ('The first one and the second one are back with them. '
             'They have three of those and will do this again. ') * 3
    assert not extract_entities(prose, 2)
    terms = 'packet header handshake matrix column key value number start end right where '
    assert set(extract_entities(terms * 3, 2)) == set(terms.split())


def test_stopword_identifiers_sql_acronyms_and_numbers_survive():
    text = ('`first` `back` ```python\nfor item in data:\n    first = back\n``` '
            'SELECT name FROM tbl WHERE flag AND NOT deleted; CAN bus TCP 120 3.14 [00:12:35] ') * 2
    entities = extract_entities(text, 2)
    assert {'first', 'back', 'for', 'from', 'where', 'and', 'not', 'can', 'tcp', '120', '3.14'} <= set(entities)
    assert not {'00', '12', '35'} & set(entities)


def test_source_labels_are_not_lecture_entities():
    text = ('# BLK01\n\n> 来源：混合\n\n'
            '[听音转录 · P01 Screen Recording 2022-01-02 at 17.40.10]\n'
            '> 来源：听音转录\n\nTCP header 20 20 bytes\n')
    assert strip_transcript_header(text) == 'TCP header 20 20 bytes\n'
    assert extract_entities(strip_transcript_header(text), 2) == {'20': 2}


def _single(ws, block, source, article):
    write_blocks(ws, [block])
    TaskWorkspace.block_path(ws, block).write_text(source, encoding='utf-8')
    module_article_path(ws.articles_dir, block).write_text(article, encoding='utf-8')


def test_full_chinese_tcp_article_is_accepted_from_frozen_evidence(make_parts, blocks_factory):
    fixtures = Path(__file__).parent / 'fixtures' / 'grounding_tcp'
    source = (fixtures / 'source.md').read_bytes()
    article = (fixtures / 'article.md').read_bytes()
    # Entire real files, frozen by reviewed hashes. No token padding or threshold override.
    assert hashlib.sha256(source).hexdigest() == '1dca95f1c00b9ba0c1e6956ab0e808ccf6d385c7aa5c6c18fc2de9eded78d7f8'
    assert hashlib.sha256(article).hexdigest() == '69b49bb63f044e5cad89ff5a58da176581e821e57f0b91026341943343f72be0'
    ws = make_parts((1,))
    block = blocks_factory(1, [1], 'TCP入门')
    _single(ws, block, source.decode(), article.decode())
    entry = check_grounding_block(ws, block, 2, DEFAULT_MIN_COVERAGE)
    assert DEFAULT_MIN_COVERAGE == 0.5
    assert entry['status'] == 'ok'
    assert entry['coverage'] >= 0.5
    assert run_stage1(dir_path=str(ws.root_dir), strict=True) == 0


def test_english_off_topic_article_cannot_pass_on_shared_grammar(make_parts, blocks_factory):
    source = ('The first computer and the second computer are back with their packets. '
              'They have many packets and will send data again. '
              'TCP packet header data handshake. ') * 8
    article = ('The first gardener and the second gardener are back with their flowers. '
               'They have many plants and will water them again. ') * 15
    ws = make_parts((1,))
    block = blocks_factory(1, [1], 'TCP')
    _single(ws, block, source, article)
    assert check_grounding_block(ws, block, 2, 0.5)['status'] == 'low_coverage'
    assert run_stage1(dir_path=str(ws.root_dir), strict=True) == 1


def _duplicate_ws(make_parts, blocks_factory, *, cid2=12345, second_start=1800):
    ws = make_parts((1,))
    blocks = []
    body = '缓存命中复用结果，缓存失效需要更新，事务隔离防止数据冲突。' * 80
    for bid, start, end, cid in [(1, 0, 1800, 12345), (2, second_start, 3600, cid2)]:
        block = blocks_factory(bid, [1], '缓存机制', span=f'P01片段{bid}')
        block['units'] = [{'source': {'cid': cid}, 'page': 1, 'source_offset_sec': start,
                           'start_sec': start, 'end_sec': end}]
        # Whole-source offset is deliberately nonzero in the lower half.
        blocks.append(block)
        TaskWorkspace.block_path(ws, block).write_text(f'# BLK{bid}\n\n> 来源：听音转录\n\n' + body)
        module_article_path(ws.articles_dir, block).write_text('# 缓存机制\n\n' + body)
    write_blocks(ws, blocks, source={'parts': [{'page': 1}]})
    return ws, blocks


def test_disjoint_same_cid_untimed_duplicate_blocks_even_with_high_coverage(make_parts, blocks_factory):
    ws, blocks = _duplicate_ws(make_parts, blocks_factory)
    issues = check_transcript_ranges_workspace(ws, blocks)
    assert len(issues) == 1 and issues[0]['block_ids'] == [1, 2]
    assert issues[0]['members'][1]['ranges'] == [[12345, 1800.0, 3600.0]]
    report = check_grounding_workspace(ws, 2, 0.5)
    assert report['source_issue'] == 2
    assert all(e['grounding_status'] == 'ok' and e['status'] == 'source_issue' for e in report['entries'])
    assert run_stage1(dir_path=str(ws.root_dir), strict=True) == 1
    assert any('来源范围不可信' in issue for issue in check_production_workspace(ws))


def test_merge_of_full_page_audio_into_each_split_block_is_guarded(make_parts, blocks_factory):
    from src.core.subtitles import merge_block_transcript

    ws, blocks = _duplicate_ws(make_parts, blocks_factory)
    full_page = TaskWorkspace.block_path(ws, blocks[0]).read_text()
    for block in blocks:
        unit = block['units'][0]
        block['segments'] = [{'page': 1, 'label': block['span'],
                              'start_sec': 0, 'end_sec': 1800,
                              'source': {'offset_sec': unit['start_sec'],
                                         'metadata': {'cid': 12345, 'title': '整集'}}}]
        merged = merge_block_transcript(block, {'missing_pages': [1]}, {1: full_page})
        assert merged['ok'] and full_page in merged['text']
        TaskWorkspace.block_path(ws, block).write_text(merged['text'])
    assert check_transcript_ranges_workspace(ws, blocks)[0]['block_ids'] == [1, 2]


@pytest.mark.parametrize('cid2,second_start', [(54321, 1800), (12345, 900)])
def test_other_cid_or_overlapping_reuse_is_not_this_source_issue(make_parts, blocks_factory, cid2, second_start):
    ws, blocks = _duplicate_ws(make_parts, blocks_factory, cid2=cid2, second_start=second_start)
    assert check_transcript_ranges_workspace(ws, blocks) == []


def _range_reviews(ws, blocks):
    evidence = ws.root_dir / 'range-comparison.txt'
    evidence.write_text('Synthetic test evidence: both independent audio ranges contain this repeated lecture.')
    reviews = []
    for block in blocks:
        u = block['units'][0]
        reviews.append({'block_id': block['block_id'], 'range_verified': True,
                        'repeated_body_verified': True, 'reviewer': 'test reviewer',
                        'reason': 'Independently checked repetition in both exact intervals.',
                        'transcript_sha256': hashlib.sha256(TaskWorkspace.block_path(ws, block).read_bytes()).hexdigest(),
                        'ranges': [[u['source']['cid'], u['start_sec'], u['end_sec']]],
                        'evidence': [{'path': evidence.name, 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest(),
                                      'method': 'Independent comparison of both audio intervals'}]})
    return {'reviews': reviews}


def test_only_current_explicit_range_evidence_exempts_duplicate(make_parts, blocks_factory):
    ws, blocks = _duplicate_ws(make_parts, blocks_factory)
    reviews = _range_reviews(ws, blocks)
    path = ws.root_dir / 'source_range_review.json'
    path.write_text(json.dumps(reviews))
    assert check_transcript_ranges_workspace(ws, blocks) == []
    (ws.root_dir / 'range-comparison.txt').write_text('Changed evidence.')
    assert check_transcript_ranges_workspace(ws, blocks)


@pytest.mark.parametrize('damage', ['range', 'source_hash', 'flag', 'missing_evidence', 'one_block', 'self_evidence'])
def test_filename_ready_or_generic_pass_cannot_exempt(make_parts, blocks_factory, damage):
    ws, blocks = _duplicate_ws(make_parts, blocks_factory)
    reviews = _range_reviews(ws, blocks)
    r = reviews['reviews'][1]
    if damage == 'range':
        r['ranges'][0][1] = 0
    elif damage == 'source_hash':
        r['transcript_sha256'] = '0' * 64
    elif damage == 'flag':
        r['range_verified'] = 'true'
    elif damage == 'missing_evidence':
        r['evidence'] = []
    elif damage == 'one_block':
        reviews['reviews'].pop()
    elif damage == 'self_evidence':
        transcript = TaskWorkspace.block_path(ws, blocks[1])
        r['evidence'][0].update(path=str(transcript), sha256=r['transcript_sha256'])
    (ws.root_dir / 'source_range_review.json').write_text(json.dumps(reviews))
    (ws.root_dir / 'manifest.json').write_text(json.dumps({'range_verified': True, 'ready': [1, 2], 'decision': 'pass'}))
    assert check_transcript_ranges_workspace(ws, blocks)
