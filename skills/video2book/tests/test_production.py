import json

from conftest import write_blocks
from src.core.quality_gate import check_production_workspace, run_production
from src.generator.integrator import ArticleIntegrator


def complete_workspace(make_parts, blocks_factory):
    ws = make_parts((1,))
    from src.core.block_plan import BlockPlan
    plan = BlockPlan.plan_from_parts([{'page': 1, 'title': '缓存机制', 'duration': 1800}])
    blocks = plan['blocks']
    BlockPlan.save(ws, plan)
    text = "缓存命中复用已有结果，更新操作需要同步处理缓存失效。" * 100
    (ws.subtitles_dir / "BLK01_P01_逐字稿.md").write_text(text, encoding="utf-8")
    (ws.articles_dir / "模块01_缓存机制_精读长文.md").write_text("# 缓存机制\n\n" + text, encoding="utf-8")
    (ws.root_dir / "note_plan.json").write_text(json.dumps(
        [{"note_id": 1, "note_title": "缓存与一致性", "blocks": [1]}]), encoding="utf-8")
    (ws.notes_dir / "笔记01_缓存与一致性_笔记.md").write_text(
        "# 缓存与一致性\n\n## 机制\n\n" + "- 命中后复用结果，更新时处理失效，失效策略影响读写一致性。\n" * 30, encoding="utf-8")
    ArticleIntegrator(ws.root_dir).run("缓存课程", blocks=blocks)
    return ws, blocks


def test_complete_production_gate(make_parts, blocks_factory, capsys):
    ws, _ = complete_workspace(make_parts, blocks_factory)
    assert check_production_workspace(ws) == []
    assert run_production(dir_path=str(ws.root_dir), as_json=True) == 0
    payload = capsys.readouterr().out
    assert '"ok": true' in payload


def test_missing_transcript_and_note_fail(make_parts, blocks_factory):
    ws, _ = complete_workspace(make_parts, blocks_factory)
    next(ws.subtitles_dir.glob("*_逐字稿.md")).unlink()
    next(ws.notes_dir.glob("*_笔记.md")).unlink()
    assert run_production(dir_path=str(ws.root_dir)) == 1


def test_article_change_rebuilds_without_force(make_parts, blocks_factory):
    ws, blocks = complete_workspace(make_parts, blocks_factory)
    article = next(ws.articles_dir.glob("*_精读长文.md"))
    article.write_text(article.read_text(encoding="utf-8") + "\n新的失效策略。", encoding="utf-8")
    assert any("尚未完整整编" in issue for issue in check_production_workspace(ws))
    ArticleIntegrator(ws.root_dir).run("缓存课程", blocks=blocks)
    assert check_production_workspace(ws) == []


def test_exclusion_requires_explicit_reason(make_parts, blocks_factory):
    ws, _ = complete_workspace(make_parts, blocks_factory)
    path = ws.root_dir / "block_plan.json"
    plan = json.loads(path.read_text(encoding="utf-8"))
    plan["source"]["parts"].append({"page": 2, "duration": 600})
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert check_production_workspace(ws)
    plan["excluded_pages"] = {"2": "重复的原声版本"}
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert check_production_workspace(ws) == []


def test_empty_workspace_never_completes(make_workspace):
    ws = make_workspace("empty")
    assert run_production(dir_path=str(ws.root_dir)) == 1


def test_duplicate_note_coverage_rejected(make_parts, blocks_factory):
    ws, _ = complete_workspace(make_parts, blocks_factory)
    (ws.root_dir / "note_plan.json").write_text(json.dumps(
        [{"note_id": 1, "note_title": "缓存与一致性", "blocks": [1, 1]}]), encoding="utf-8")
    assert any("各一次" in issue for issue in check_production_workspace(ws))


def test_unplanned_note_rejected(make_parts, blocks_factory):
    ws, _ = complete_workspace(make_parts, blocks_factory)
    (ws.notes_dir / "笔记99_旧主题_笔记.md").write_text("旧笔记" * 500, encoding="utf-8")
    assert "存在计划外笔记" in check_production_workspace(ws)


def test_source_change_invalidates_registered_article(make_parts, blocks_factory):
    from src.core.taskbook import export_block_article_task
    from src.core.workspace import find_module_article
    from src.bookcore.state import statuses

    ws, blocks = complete_workspace(make_parts, blocks_factory)
    transcript = next(ws.subtitles_dir.glob("*_逐字稿.md"))
    article = next(ws.articles_dir.glob("*_精读长文.md"))
    export_block_article_task(ws, blocks[0], transcript_file=transcript, article_type="learning")
    transcript.write_text(transcript.read_text(encoding="utf-8") + "\n更新来源。", encoding="utf-8")
    assert find_module_article(ws.articles_dir, blocks[0]) is None
    export_block_article_task(ws, blocks[0], transcript_file=transcript, article_type="learning")
    assert statuses(ws.root_dir)[0]["state"] == "stale"
    article.write_text(article.read_text(encoding="utf-8") + "\n依据更新来源复核。", encoding="utf-8")
    assert find_module_article(ws.articles_dir, blocks[0]) == article


def test_status_uses_shared_report_without_migration(make_parts, blocks_factory, capsys):
    from types import SimpleNamespace
    from src.cli import cmd_check

    ws, _ = complete_workspace(make_parts, blocks_factory)
    capsys.readouterr()
    assert cmd_check(SimpleNamespace(status=True, base_dir=None, task=None, dir=str(ws.root_dir))) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == 1 and result["tool"] == "video2book"
    assert any(i["code"] == "untracked" for i in result["issues"])
    assert not (ws.root_dir / "production_state.json").exists()


def test_placeholder_source_blocks_even_an_existing_book(make_parts, blocks_factory):
    ws, _ = complete_workspace(make_parts, blocks_factory)
    transcript = next(ws.subtitles_dir.glob('*_逐字稿.md'))
    transcript.write_text('# 来源\n\n（本集音频以音乐/无人声为主，自动听音转录未得到可识别语音。）\n')
    assert any('来源不完整' in s for s in check_production_workspace(ws))


def test_partial_block_placeholder_is_not_coverage():
    from src.core.quality_gate import transcript_source_issues
    text = '第一集真实内容。\n\n（本集音频以音乐/无人声为主，自动听音转录未得到可识别语音。）\n'
    assert transcript_source_issues(text)
    assert transcript_source_issues('# BLK01\n\n> 来源：自动字幕\n')
    assert not transcript_source_issues('# BLK01\n\n> 来源：自动字幕\n\n简短但真实的正文。')
    assert not transcript_source_issues('课堂讨论“未得到可识别语音”的识别错误。')
    assert transcript_source_issues('> 来源：B站平台字幕（语料库回灌）。整集字幕按块时间区间等比切片,非精确对齐。\n不相关的正文。')
    assert transcript_source_issues('> ⚠ 本稿**不完整**：P01 未取到字幕。\n另一集的正文。')
