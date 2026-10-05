"""Run the same contract suite against all independently bundled copies."""
import importlib
import importlib.util
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(params=["video2book", "wechat2book", "book2book", "chat2book"])
def core(request):
    workspace = Path(__file__).resolve().parents[4]
    if request.param == "video2book":
        folder = Path(__file__).resolve().parents[1] / "src/bookcore"
    else:
        folder = workspace / request.param / "src" / request.param / "_bookcore"
    if not folder.is_dir():
        pytest.skip("Sibling checkout is not part of standalone skill installation")
    name = "contract_" + request.param
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, folder / "__init__.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return SimpleNamespace(**{part: importlib.import_module(name + "." + part)
                              for part in ("contracts", "state", "publish", "assembly", "article_body", "checks", "io")})


def task(core, *, required=True):
    return core.contracts.Task("article:1", "article.md", ("source.md",), required=required)


def test_task_lifecycle_and_idempotent_export(core, tmp_path):
    (tmp_path / "source.md").write_text("original", encoding="utf-8")
    core.state.register(tmp_path, [task(core)])
    assert core.state.statuses(tmp_path)[0]["state"] == "pending"
    (tmp_path / "article.md").write_text("first output", encoding="utf-8")
    assert core.state.report(tmp_path, "test").ok
    (tmp_path / "source.md").write_text("updated", encoding="utf-8")
    assert core.state.statuses(tmp_path)[0]["state"] == "stale"
    core.state.register(tmp_path, [task(core)])
    core.state.register(tmp_path, [task(core)])
    assert not core.state.report(tmp_path, "test").ok
    (tmp_path / "article.md").write_text("rewritten output", encoding="utf-8")
    assert core.state.statuses(tmp_path)[0]["state"] == "ready"


def test_initial_source_materialization_can_bind_before_dispatch(core, tmp_path):
    core.state.register(tmp_path, [task(core)])
    (tmp_path / "source.md").write_text("newly transcribed", encoding="utf-8")
    core.state.activate(tmp_path, "article:1")
    assert core.state.statuses(tmp_path)[0]["state"] == "pending"
    (tmp_path / "article.md").write_text("written from transcript", encoding="utf-8")
    assert core.state.statuses(tmp_path)[0]["state"] == "ready"
    (tmp_path / "source.md").write_text("modified transcript", encoding="utf-8")
    core.state.activate(tmp_path, "article:1")
    assert core.state.statuses(tmp_path)[0]["state"] == "stale"


def test_legacy_check_does_not_write_or_certify_freshness(core, tmp_path):
    report = core.state.report(tmp_path, "legacy")
    assert report.ok and report.issues[0].code == "untracked"
    assert not list(tmp_path.iterdir())


def test_changed_article_invalidates_note(core, tmp_path):
    article = tmp_path / "article.md"
    article.write_text("article", encoding="utf-8")
    note = core.contracts.Task("note:1", "note.md", ("article.md",))
    core.state.register(tmp_path, [note])
    (tmp_path / "note.md").write_text("note", encoding="utf-8")
    article.write_text("changed", encoding="utf-8")
    assert not core.state.report(tmp_path, "test").ok


def test_optional_unwritten_task_is_not_a_delivery_failure(core, tmp_path):
    core.state.register(tmp_path, [task(core, required=False)])
    assert core.state.report(tmp_path, "test").ok


@pytest.mark.parametrize("name", ["../outside", "/tmp/outside", "sub/../../outside", "a\\b"])
def test_paths_reject_escape(core, tmp_path, name):
    with pytest.raises(ValueError):
        core.io.relative_path(tmp_path, name)


def test_assembly_unchanged_preserves_mtime_and_removes_stale(core, tmp_path):
    book = tmp_path / "book.md"
    rendered = {book.name: "# Book\n"}
    core.assembly.write_books(tmp_path, rendered, "*.md")
    before = book.stat().st_mtime_ns
    (tmp_path / "old.md").write_text("old", encoding="utf-8")
    core.assembly.write_books(tmp_path, rendered, "*.md")
    assert book.stat().st_mtime_ns == before
    assert not (tmp_path / "old.md").exists()


def test_passthrough_retains_author_opening(core, tmp_path):
    path = tmp_path / "article.md"
    path.write_text("# Title\n\n> Original opening\n\n---\n\nBody\n", encoding="utf-8")
    assert "Original opening" not in core.article_body.read_article_body(path)
    assert "Original opening" in core.article_body.read_article_body(path, preserve_header=True)


def publication(core, tmp_path, **product_options):
    ws = tmp_path / "workspace"
    (ws / "books").mkdir(parents=True)
    (ws / "books/book.md").write_text("# Book\n", encoding="utf-8")
    profile = core.contracts.Profile("test", (
        core.contracts.Product("books", ("*.md",), required=True, **product_options),))
    return ws, tmp_path / "courses", {
        "profile": profile, "subjects": {"cs": "Computing"}, "validate": lambda ws: None,
        "readme": lambda ws, title, direction, files: "# " + title + "\n"}


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_publish_is_idempotent_and_whitelisted(core, tmp_path):
    ws, root, kwargs = publication(core, tmp_path)
    core.publish.publish(ws, root, "cs/course", "Course", **kwargs)
    (root / "cs/course/secret.txt").write_text("stale", encoding="utf-8")
    result = core.publish.publish(ws, root, "cs/course", "Course", **kwargs)
    assert result["copied"]["books"] == 0
    assert not (root / "cs/course/secret.txt").exists()
    assert json.loads((root / "course_catalog.json").read_text())["schema_version"] == 2


@pytest.mark.parametrize("failure", ["course_catalog.json", "README.md"])
def test_publish_rollback_restores_metadata_and_course(core, tmp_path, monkeypatch, failure):
    ws, root, kwargs = publication(core, tmp_path)
    core.publish.publish(ws, root, "cs/course", "Course", **kwargs)
    before = snapshot(root)
    (ws / "books/book.md").write_text("# New book\n", encoding="utf-8")
    replace = Path.replace

    def fail(self, target):
        if self.name == failure and Path(target) == root / failure:
            raise OSError("injected install failure")
        return replace(self, target)

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="injected"):
        core.publish.publish(ws, root, "cs/course", "Changed", **kwargs)
    assert snapshot(root) == before
    assert not list(root.glob(".publish-*"))


def test_publish_lock_prevents_concurrent_writer(core, tmp_path):
    ws, root, kwargs = publication(core, tmp_path)
    root.mkdir()
    (root / ".production-publish.lock").write_text("active", encoding="utf-8")
    with pytest.raises(ValueError, match="publication"):
        core.publish.publish(ws, root, "cs/course", "Course", **kwargs)
    assert (root / ".production-publish.lock").read_text() == "active"


def test_read_only_target_is_never_created(core, tmp_path):
    ws, root, kwargs = publication(core, tmp_path)
    kwargs["profile"] = core.contracts.Profile("video2book", (), read_only_target=True)
    with pytest.raises(ValueError, match="read-only"):
        core.publish.publish(ws, root, "cs/course", "Course", **kwargs)
    assert not root.exists()


def test_preserve_existing_source_policy(core, tmp_path):
    ws, root, kwargs = publication(core, tmp_path, preserve_existing=True)
    core.publish.publish(ws, root, "cs/course", "Course", **kwargs)
    (ws / "books/book.md").write_text("new source representation", encoding="utf-8")
    core.publish.publish(ws, root, "cs/course", "Course", **kwargs)
    assert (root / "cs/course/books/book.md").read_text() == "# Book\n"


def test_missing_required_products_block_publication(core, tmp_path):
    ws, root, kwargs = publication(core, tmp_path)
    (ws / "books/book.md").unlink()
    with pytest.raises(ValueError, match="missing_product"):
        core.publish.publish(ws, root, "cs/course", "Course", **kwargs)
    assert not root.exists()


def test_bundle_matches_release_hashes(core):
    folder = Path(core.io.__file__).parent
    release = json.loads((folder / "RELEASE.json").read_text())
    package = importlib.import_module(core.io.__package__)
    assert package.VERSION == release["version"]
    for name, digest in release["sha256"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("unit", ["char", "second", "page"])
def test_coverage_contract_keeps_units_distinct(core, unit):
    span = core.contracts.SourceRange
    source = [span("source", 0, 100, unit)]
    assert core.checks.check_coverage(source, [span("source", 0, 100, unit)], tool="test").ok
    for bad in ([span("unknown", 0, 100, unit)], [span("source", 1, 100, unit)],
                [span("source", 0, 101, unit)], [span("source", 0, 100, "different")]):
        assert not core.checks.check_coverage(source, bad, tool="test").ok
    overlapping = [span("source", 0, 80, unit), span("source", 70, 100, unit)]
    assert not core.checks.check_coverage(source, overlapping, tool="test").ok
    assert core.checks.check_coverage(source, overlapping, tool="test", allow_overlap=True).ok


def test_retired_tasks_do_not_block_new_plan(core, tmp_path):
    core.state.register(tmp_path, [task(core)])
    core.state.register(tmp_path, [], replace_prefix="article:")
    assert core.state.report(tmp_path, "test").ok
    assert core.state.statuses(tmp_path) == []


def test_status_is_read_only(core, tmp_path):
    core.state.register(tmp_path, [task(core)])
    before = snapshot(tmp_path)
    core.state.report(tmp_path, "test")
    core.state.statuses(tmp_path)
    assert snapshot(tmp_path) == before


def test_nested_list_fences_keep_wechat_fix(core):
    from_text = core.checks.lint_render("- " + chr(96) * 3 + "text\n  body\n  " + chr(96) * 3)
    assert not from_text["fences_unbalanced"]
